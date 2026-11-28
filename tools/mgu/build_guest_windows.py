"""Build the ARM64 Linux guest with a portable Windows Zig toolchain."""
import subprocess
import sys
from pathlib import Path


def build(sysroot, output, zig):
    src = Path(__file__).resolve().parents[2] / 'src' / 'mgu22'
    output = Path(output).resolve()
    sysroot = Path(sysroot).resolve()
    output.mkdir(parents=True, exist_ok=True)
    libs = [f'-L{sysroot / "lib"}', f'-L{sysroot / "usr" / "lib"}']
    libc = 'libc.so.6'

    def run(*args):
        subprocess.check_call(args, cwd=src)

    def compile_object(source):
        obj = output / (Path(source).stem + '.o')
        run(zig, 'cc', '-target', 'aarch64-linux-gnu', '-ffreestanding', '-fPIC', '-O2',
            '-fno-stack-protector', '-fno-builtin-malloc', '-Wno-everything', '-c', source, '-o', obj)
        return obj

    def library(name, obj, *dependencies, options=()):
        run(zig, 'ld.lld', '-shared', '-z', 'noexecstack', '--hash-style=gnu', *options,
            '-soname', name, '-o', output / name, obj, *libs, f'-L{output}',
            *(f'-l:{lib}' for lib in dependencies))

    def executable(name, *dependencies):
        run(zig, 'ld.lld', '--dynamic-linker=/lib/ld-linux-aarch64.so.1', '-z', 'noexecstack',
            '--hash-style=gnu', '--unresolved-symbols=ignore-in-shared-libs', '-o', output / name,
            crt, compile_object(name + '.c'), *libs, f'-l:{libc}', *(f'-l:{lib}' for lib in dependencies))

    run(sys.executable, 'gen.py')
    crt = compile_object('crt.c')
    library('libcod.so.0', compile_object('libcod.c'), libc)
    library('libEGL.so.1', compile_object('guest_egl.c'), libc, 'libwayland-client.so.0')
    empty = output / 'empty.c'
    empty.write_text('int idemu_gles_stub;\n', encoding='ascii')
    library('libGLESv2.so.2', compile_object(empty), 'libEGL.so.1')
    library('libusb-1.0.so.0', compile_object('usbfake/libusb_fake.c'), libc)
    library('libudev.so.1', compile_object('usbfake/libudev_fake.c'), libc,
            options=('--version-script=usbfake/libudev.map',))
    library('libidemuhmi.so', compile_object('hmihook.c'), libc)
    executable('ustk')
    executable('idemuinput')
    executable('idemuusb', 'libdbus-1.so.3')
    executable('idemuwl', 'libwayland-server.so.0', 'libivi-application.so.1', 'libivi-controller.so.1')
