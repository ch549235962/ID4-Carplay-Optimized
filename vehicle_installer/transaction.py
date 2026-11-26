"""Two-directory activation with an exit-trap rollback, using QNX POSIX sh only."""
from .payload import RT, PLUGIN
from .remote import quote as q


def commit_script(tx, existing, wanted):
    """Never delete a live directory; retain the previous directories in tx."""
    lines = ['#!/bin/sh', 'set -eu', 'r_old=0; r_new=0; p_old=0; p_new=0',
             'undo() {', ' rc=$?', ' trap - 0 HUP INT TERM', ' set +e', ' ok=1']
    for label, root in [('p', PLUGIN), ('r', RT)]:
        lines += [f' if test "${label}_new" = 1; then mv {q(root)} {q(tx+"/failed-"+label)} || ok=0; fi',
                  f' if test "${label}_old" = 1; then mv {q(tx+"/old-"+label)} {q(root)} || ok=0; fi']
    lines += [f' if test "$ok" = 1; then echo rolled-back > {q(tx+"/phase")}; else echo recovery-required > {q(tx+"/phase")}; fi',
              f' rm -f {q(tx+"/pid")}', ' exit "${rc:-1}"', '}',
              'trap undo 0', "trap 'exit 1' HUP INT TERM"]
    # Check every assumption before the first rename.
    for label, root in [('r', RT), ('p', PLUGIN)]:
        lines += [f'test ! -e {q(tx+"/old-"+label)}', f'test ! -L {q(root)}',
                  f'test {"-d" if existing[root] else "! -e"} {q(root)}']
        if wanted[root]:
            lines.append(f'test -d {q(tx+"/new-"+label)}')
    lines += [f'echo "$$" > {q(tx+"/pid")}', f'echo committing > {q(tx+"/phase")}']
    for label, root in [('r', RT), ('p', PLUGIN)]:
        if existing[root]:
            lines += [f'mv {q(root)} {q(tx+"/old-"+label)}', f'{label}_old=1']
        if wanted[root]:
            lines += [f'mv {q(tx+"/new-"+label)} {q(root)}', f'{label}_new=1']
    lines += [f'echo committed > {q(tx+"/phase")}', f'rm -f {q(tx+"/pid")}', 'trap - 0 HUP INT TERM', 'exit 0']
    return ('\n'.join(lines)+'\n').encode()


def rollback_script(tx, existing, wanted, token):
    lines = ['#!/bin/sh', 'set -eu']
    # Require our token on every newly activated directory before touching any.
    for label, root in [('r', RT), ('p', PLUGIN)]:
        if wanted[root]:
            lines.append(f'test "$(cat {q(root+"/.id4-installer-token")})" = {q(token)}')
        else:
            lines.append(f'test ! -e {q(root)}')
        if existing[root]:
            lines.append(f'test -d {q(tx+"/old-"+label)}')
        lines.append(f'test ! -e {q(tx+"/failed-"+label)}')
    for label, root in [('p', PLUGIN), ('r', RT)]:
        if wanted[root]:
            lines.append(f'mv {q(root)} {q(tx+"/failed-"+label)}')
        if existing[root]:
            lines.append(f'mv {q(tx+"/old-"+label)} {q(root)}')
    lines += [f'echo rolled-back > {q(tx+"/phase")}', 'exit 0']
    return ('\n'.join(lines)+'\n').encode()
