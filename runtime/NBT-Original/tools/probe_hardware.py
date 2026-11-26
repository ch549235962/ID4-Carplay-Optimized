"""Build only the validated 512 MiB / 1 vCPU envelope from a local dependency."""
import importlib.util
from pathlib import Path
R=Path(__file__).resolve().parents[1]
SOURCE=R.parent/'NBT-Dev/src/BMW-NBT-Emulator'

def envelope(image,output,ram,cpus,smp_adapter=False):
    if ram!=512 or cpus!=1 or smp_adapter:
        raise ValueError('This optimization package supports the validated 512 MiB / 1 vCPU profile only')
    file=SOURCE/'outputs/NBT_emulation_research/boot_experiment.py'
    spec=importlib.util.spec_from_file_location('nbt_boot_local',file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.make_envelope(image,output,provide_memory=True,memory_layout='nbt-map',startup_max_cpus=1,qemu_clock_adapter=True)
