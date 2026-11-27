"""Small Chinese desktop GUI. All network operations run outside Tk's UI thread."""
from __future__ import annotations
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from .engine import Installer
from .payload import data_directory, load_lock, InstallError

VERSION = '0.2.1'


class App:
    def __init__(self, window, root=None):
        self.window = window
        self.root = root or data_directory()
        self.events = queue.Queue()
        self.busy = False
        self.lines = []
        window.title('ID4 CarPlay 一键安装 · '+VERSION)
        window.geometry('650x650'); window.minsize(620, 600)
        window.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(window)
        if 'clam' in style.theme_names(): style.theme_use('clam')
        style.configure('Title.TLabel', font=('Arial', 23, 'bold'))
        style.configure('Primary.TButton', padding=(18,12), font=('Arial',13,'bold'))
        frame = ttk.Frame(window, padding=24); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='ID4 CarPlay',style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame,text='原始 BMW NBT · ENET 安装 · 实验版（尚未实车验证）',font=('Arial',12)).pack(anchor='w',pady=(4,12))
        ttk.Label(frame,text='用 ENET 网线连接车辆，保持车辆稳定供电。\n车机需提前开通 SSH，并准备 root 密码。',wraplength=590).pack(anchor='w')
        form=ttk.Frame(frame);form.pack(fill='x',pady=(16,8));form.columnconfigure(1,weight=1)
        self.host=tk.StringVar(value='169.254.199.99');self.password=tk.StringVar()
        self.port=tk.StringVar(value='22');self.gateway=tk.StringVar();self.offline=tk.StringVar()
        self.inputs=[]
        for row,(label,var,show) in enumerate([('车机地址',self.host,''),('root 密码',self.password,'•')]):
            ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',padx=(0,16),pady=6)
            field=ttk.Entry(form,textvariable=var,show=show,font=('Arial',13));field.grid(row=row,column=1,sticky='ew',pady=6)
            self.inputs.append(field)
        self.install_button=ttk.Button(frame,text='一键安装并重启',style='Primary.TButton',command=lambda:self.start('install'))
        self.install_button.pack(fill='x',pady=(8,8));self.inputs.append(self.install_button)
        row=ttk.Frame(frame);row.pack(fill='x')
        for text,command in [('只检查连接',lambda:self.start('check')),('高级选项',self.toggle_advanced),('打开备份 / 日志',self.open_data)]:
            button=ttk.Button(row,text=text,command=command);button.pack(side='left',padx=(0,8));self.inputs.append(button)
        self.advanced=ttk.Frame(frame,padding=(0,12))
        self.advanced.columnconfigure(1,weight=1)
        for i,(label,var) in enumerate([('SSH 端口',self.port),('车辆网关（留空自动找）',self.gateway)]):
            ttk.Label(self.advanced,text=label).grid(row=i,column=0,sticky='w',pady=4)
            entry=ttk.Entry(self.advanced,textvariable=var);entry.grid(row=i,column=1,sticky='ew',pady=4);self.inputs.append(entry)
        button=ttk.Button(self.advanced,text='选择离线官方 ZIP',command=self.choose_zip)
        button.grid(row=2,column=0,sticky='w',pady=4);self.inputs.append(button)
        ttk.Label(self.advanced,textvariable=self.offline,wraplength=300).grid(row=2,column=1,sticky='w')
        for rownum,text,command in [(3,'恢复上次安装前备份',self.confirm_restore),(4,'清除记住的 SSH 身份',self.forget_identity)]:
            button=ttk.Button(self.advanced,text=text,command=command);button.grid(row=rownum,column=0,columnspan=2,sticky='w',pady=4);self.inputs.append(button)
        self.status=tk.StringVar(value='准备就绪 · 官方版本 '+load_lock()['version'])
        ttk.Label(frame,textvariable=self.status,wraplength=590).pack(anchor='w',pady=(18,6))
        self.progress=ttk.Progressbar(frame,maximum=100);self.progress.pack(fill='x')
        self.output=tk.Text(frame,height=8,wrap='word',font=('Arial',11),state='disabled',relief='flat',padx=8,pady=8)
        self.output.pack(fill='both',expand=True,pady=(10,4))
        ttk.Label(frame,text='安装的是 JayJay 原车插件；本地模拟器的性能改动不会写入车辆。\n首次连接 iPhone 可能需要等待 2–3 分钟。',wraplength=590,foreground='#555555').pack(anchor='w',pady=(5,0))
        window.after(80,self.drain)

    def toggle_advanced(self):
        if self.advanced.winfo_manager():
            self.advanced.pack_forget();self.window.geometry('650x650')
        else:
            # Pack before the status and progress area.
            children=self.advanced.master.pack_slaves()
            self.advanced.pack(fill='x',before=children[-5]);self.window.geometry('650x850')

    def choose_zip(self):
        path=filedialog.askopenfilename(title='选择固定版本的 JayJay 官方安装包',filetypes=[('官方安装包','*.zip')])
        if path:self.offline.set(path)

    def open_data(self):
        if sys.platform=='darwin':subprocess.Popen(['open',str(self.root)])
        elif os.name=='nt':os.startfile(str(self.root))
        else:subprocess.Popen(['xdg-open',str(self.root)])

    def forget_identity(self):
        if messagebox.askyesno('更换车机','清除本机记住的 SSH 身份？仅在更换车辆或确认 SSH 密钥已更换时使用。'):
            (self.root/'known-headunits.json').unlink(missing_ok=True)
            self.append('已清除本机记住的 SSH 身份。')

    def confirm_restore(self):
        if messagebox.askyesno('恢复安装前备份','将恢复这台车机最近一次操作前的插件文件。\n首次安装前没有插件时，会移走本次安装的插件。\n当前文件仍会先备份。继续恢复并请求重启吗？'):
            self.start('restore')

    def append(self,line):
        stamp=time.strftime('%H:%M:%S')
        self.lines.append(f'[{stamp}] {line}')
        self.output.configure(state='normal');self.output.insert('end',line+'\n');self.output.see('end');self.output.configure(state='disabled')

    def start(self, action):
        if self.busy:return
        try:
            port=int(self.port.get())
            if not 1<=port<=65535:raise ValueError()
        except ValueError:
            messagebox.showerror('端口无效','请输入 1–65535 之间的 SSH 端口。');return
        host=self.host.get().strip();password=self.password.get()
        if not password:
            messagebox.showinfo('需要 root 密码','请输入已开通 SSH 的车机 root 密码。安装器不能自动开通 SSH。');return
        values={'host':host,'password':password,'port':port}
        if action!='check':values.update(gateway_ip=self.gateway.get().strip(),offline=Path(self.offline.get()) if self.offline.get() else None,restore=action=='restore')
        self.busy=True;self.progress['value']=0
        for widget in self.inputs:widget.configure(state='disabled')
        self.append({'install':'开始安装：先检查和备份，再暂存并校验。','restore':'开始恢复安装前备份。','check':'仅检查连接，不写入车辆文件。'}[action])
        def worker():
            try:
                installer=Installer(self.root,lambda title,fraction:self.events.put(('progress',title,fraction)))
                result=installer.check(**values) if action=='check' else installer.operate(**values)
                self.events.put(('done',result['message']))
            except Exception as error:
                # Do not dump SSH authentication arguments, process environment, or phone key files.
                if isinstance(error,InstallError):message=str(error)
                else:message='操作未完成（'+type(error).__name__+'）。请保留日志和备份，检查连接后再处理。'
                self.events.put(('error',message))
            finally:
                values['password']=''
        threading.Thread(target=worker,daemon=True).start()

    def drain(self):
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=='progress':
                    self.status.set(event[1]);self.progress['value']=event[2]*100
                    self.append(event[1])
                else:
                    self.busy=False;self.password.set('')
                    for widget in self.inputs:widget.configure(state='normal')
                    self.status.set('操作完成' if event[0]=='done' else '操作已停止，请查看下方说明')
                    self.append(event[1]);self.save_log()
                    if event[0]=='error':messagebox.showerror('需要处理',event[1])
        except queue.Empty:pass
        self.window.after(80,self.drain)

    def save_log(self):
        folder=self.root/'logs';folder.mkdir(exist_ok=True)
        path=folder/(time.strftime('%Y%m%d-%H%M%S')+'.log')
        with os.fdopen(os.open(path,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600),'w',encoding='utf-8') as file:file.write('\n'.join(self.lines))

    def close(self):
        if self.busy:
            messagebox.showinfo('操作进行中','正在操作车机，请保持供电和连接，等待本次操作结束后再关闭。');return
        if self.lines:self.save_log()
        self.window.destroy()


def main():
    import argparse
    import tempfile
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    window=tk.Tk()
    if args.self_test:
        window.withdraw()
        with tempfile.TemporaryDirectory() as temp:
            app=App(window,Path(temp))
            app.toggle_advanced();app.toggle_advanced();window.update_idletasks()
            assert app.host.get()=='169.254.199.99' and app.install_button['text']=='一键安装并重启'
            assert load_lock()['version']=='2026.11.26'
            app.events.put(('progress','自检',.5));app.drain()
            assert app.progress['value']==50
            from .remote import Remote
            import cryptography
            import ssl,certifi
            context=ssl.create_default_context(cafile=certifi.where())
            assert context.cert_store_stats()['x509_ca']>0
            report={'ok':True,'app_version':VERSION,'platform':sys.platform,'python':sys.version.split()[0],
                    'tk':window.tk.call('info','patchlevel'),'payload_version':load_lock()['version'],
                    'bundled_ca_certificates':context.cert_store_stats()['x509_ca'],'network_used':False}
            if args.report:args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.destroy();return
    App(window);window.mainloop()
