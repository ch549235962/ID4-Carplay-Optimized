"""Computer-side gauge identification window. No head-unit write controls."""
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from .identify import IdentificationReader
from .provision import plan
from vehicle_installer.payload import data_directory
from vehicle_installer.remote import private_json


class GaugeWindow:
    def __init__(self, window):
        self.window = window
        self.events = queue.Queue()
        self.report = None
        self.busy = False
        window.title('NBT 温度表 · 电脑端车辆配置（开发版）')
        window.geometry('650x540')
        box = ttk.Frame(window, padding=22); box.pack(fill='both', expand=True)
        ttk.Label(box, text='NBT 车辆仪表配置', font=('Arial', 22, 'bold')).pack(anchor='w')
        ttk.Label(box, text='首个候选车型：2014 F20 N13；车型提示不能代替 ECU 识别。\n'
                  '当前已验证实车配置：0。此版本只读取身份、生成待验证任务包。',
                  wraplength=600).pack(anchor='w', pady=10)
        self.host = tk.StringVar(); self.vin = tk.StringVar(); self.ecu = tk.StringVar(value='12')
        self.vehicle = tk.StringVar(value='2014 F20 N13')
        form = ttk.Frame(box); form.pack(fill='x'); form.columnconfigure(1, weight=1)
        for i, (label, value) in enumerate([('车辆网关 IPv4（非车机 IP）', self.host),
                                          ('发动机 ECU 地址（十六进制）', self.ecu),
                                          ('预期 VIN（可留空，用于核对）', self.vin),
                                          ('车型提示（不作为匹配依据）', self.vehicle)]):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky='w', padx=(0,12), pady=5)
            ttk.Entry(form, textvariable=value).grid(row=i, column=1, sticky='ew', pady=5)
        row = ttk.Frame(box); row.pack(fill='x', pady=12)
        self.read_button = ttk.Button(row, text='通过 ENET 读取身份', command=self.identify)
        self.read_button.pack(side='left')
        self.load_button = ttk.Button(row, text='导入本地身份报告', command=self.load)
        self.load_button.pack(side='left', padx=8)
        self.export_button = ttk.Button(row, text='生成待验证配置包', command=self.export, state='disabled')
        self.export_button.pack(side='left')
        self.status = tk.StringVar(value='未连接车辆；不会自动连接或发送任何请求。')
        ttk.Label(box, textvariable=self.status, wraplength=600).pack(anchor='w')
        ttk.Label(box, text='电脑负责识别、匹配和配置生成。未来车机端仅保存选定配置，\n'
                  '温度低频更新、压力按需更新，离开仪表页面停止读取。', wraplength=600).pack(anchor='w', pady=12)
        self.output = tk.Text(box, height=9, state='disabled', wrap='word')
        self.output.pack(fill='both', expand=True)
        window.after(100, self.drain)

    def show(self, text):
        self.output.configure(state='normal'); self.output.delete('1.0', 'end')
        self.output.insert('end', text); self.output.configure(state='disabled')

    def identify(self):
        if self.busy: return
        try:
            reader = IdentificationReader(self.host.get().strip(), int(self.ecu.get(), 16))
        except ValueError:
            messagebox.showerror('参数不正确', '请输入车辆网关 IPv4 和十六进制 ECU 地址。', parent=self.window); return
        self.busy = True; self.report = None; self.export_button.configure(state='disabled')
        self.read_button.configure(state='disabled'); self.load_button.configure(state='disabled')
        self.status.set('仅读取 VIN、零件号、软件号和软件版本；不改变诊断会话、不写车辆。')
        def worker():
            try: self.events.put(('report', reader.collect()))
            except Exception as error: self.events.put(('error', type(error).__name__))
        threading.Thread(target=worker, daemon=True).start()

    def load(self):
        file = filedialog.askopenfilename(parent=self.window, filetypes=[('身份报告', '*.json')])
        if not file: return
        try:
            path = Path(file)
            if path.stat().st_size > 65536: raise ValueError('报告过大')
            self.accept(json.loads(path.read_text('utf-8')))
        except (ValueError, KeyError, OSError):
            self.report = None; self.export_button.configure(state='disabled')
            messagebox.showerror('读取失败', '报告内容不完整或格式不正确。', parent=self.window)

    def accept(self, report):
        self.report = None; self.export_button.configure(state='disabled')
        value = plan(report, self.vin.get(), self.vehicle.get())
        private_json(data_directory()/'gauges/identity-private.json', report)
        self.report = report
        self.show(json.dumps(value, ensure_ascii=False, indent=2))
        self.status.set('已读取完整身份；无已验证的匹配配置，禁止生成刷写包。')
        self.export_button.configure(state='normal')

    def export(self):
        if self.report is None: return
        try: value = plan(self.report, self.vin.get(), self.vehicle.get())
        except ValueError as error:
            messagebox.showerror('匹配失败', str(error), parent=self.window); return
        file = filedialog.asksaveasfilename(parent=self.window, defaultextension='.json',
                                           initialfile='F20-N13-needs-validation.json')
        if file:
            private_json(Path(file), value)
            self.status.set('已生成待验证任务包；deployable=false，不可刷入车机。')

    def drain(self):
        try:
            while True:
                kind, data = self.events.get_nowait(); self.busy = False
                self.read_button.configure(state='normal'); self.load_button.configure(state='normal')
                if kind == 'report':
                    try: self.accept(data)
                    except (ValueError, KeyError):
                        private_json(data_directory()/'gauges/identity-private.json', data)
                        self.status.set('ECU 身份读取不完整，已保存本地报告；不生成刷写配置。')
                        self.show(json.dumps(data.get('errors', {}), ensure_ascii=False, indent=2))
                else: self.status.set('读取未完成：' + data)
        except queue.Empty: pass
        if self.window.winfo_exists(): self.window.after(100, self.drain)
