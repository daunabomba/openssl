import subprocess
import os
import multiprocessing
import shutil
from pathlib import Path
from mods.utils import get_target_triple
from mods import colors

def get_env():
    env = os.environ.copy()
    # Path to our host-built LLVM tools
    project_root = Path(__file__).parent.parent.parent
    host_bin = project_root / "bld" / "tools" / "bin"
    env["PATH"] = f"{host_bin}:{env.get('PATH', '')}"
    return env

def target_configure(staging_dir: Path, target_dir: Path, arch="x32"):
    colors.info(f"OpenSSL: target_configure ({arch})")
    repo_root = Path(__file__).parent
    project_root = repo_root.parent.parent
    
    std_flags = os.environ.get("CFLAGS", "")
    static_flags = os.environ.get("CFLAGS_STATIC", std_flags)
    
    lld_path = project_root / "bld" / "tools" / "bin" / "ld.lld"
    
    if arch == "x32":
        openssl_target = "linux-x32"
    elif arch == "x86_64":
        openssl_target = "linux-x86_64"
    elif arch == "aarch64":
        openssl_target = "linux-aarch64"
    elif arch == "riscv64":
        openssl_target = "linux-generic64" # OpenSSL might need specific target for riscv64, but linux-generic64 is a safe bet for musl
    else:
        openssl_target = "linux-generic64"
    
    # Create a linker wrapper that filters out Scrt1.o for shared libraries.
    ld_wrapper = repo_root / "ld-wrapper"
    with open(ld_wrapper, "w") as f:
        f.write("#!/bin/bash\n")
        f.write("is_shared=0\n")
        f.write("for arg in \"$@\"; do\n")
        f.write("  if [ \"$arg\" = \"-shared\" ]; then is_shared=1; break; fi\n")
        f.write("done\n")
        f.write("new_args=()\n")
        f.write("for arg in \"$@\"; do\n")
        f.write("  case \"$arg\" in\n")
        f.write("    *Scrt1.o)\n")
        f.write("      if [ \"$is_shared\" -eq 1 ]; then continue; fi\n")
        f.write("      ;;\n")
        f.write("  esac\n")
        f.write("  new_args+=(\"$arg\")\n")
        f.write("done\n")
        f.write(f"exec {lld_path} \"${{new_args[@]}}\"\n")
    ld_wrapper.chmod(0o755)

    cmd = [
        "./Configure",
        openssl_target,
        "--prefix=/usr",
        "--libdir=lib",
        "--openssldir=/etc/ssl",
        "shared",
        "no-tests",
        f"CC=clang {std_flags} --ld-path={ld_wrapper}",
        f"LDFLAGS={static_flags}",
        "AR=llvm-ar",
        "NM=llvm-nm",
        "RANLIB=llvm-ranlib"
    ]
    subprocess.run(cmd, cwd=repo_root, env=get_env(), check=True)

def target_build(staging_dir: Path, target_dir: Path, arch="x32"):
    colors.info(f"OpenSSL: target_build")
    repo_root = Path(__file__).parent
    make_jobs = multiprocessing.cpu_count()
    subprocess.run(["make", f"-j{make_jobs}"], cwd=repo_root, env=get_env(), check=True)

def target_install(staging_dir: Path, target_dir: Path, arch="x32"):
    colors.info(f"OpenSSL: target_install")
    repo_root = Path(__file__).parent
    
    # 1. Install to staging (headers, libs, exe)
    colors.info(f"OpenSSL: installing to staging {staging_dir}")
    subprocess.run(["make", f"DESTDIR={staging_dir}", "install"], cwd=repo_root, env=get_env(), check=True)
    
    # 2. Install to target (libs and executables only)
    colors.info(f"OpenSSL: installing to target {target_dir}")
    subprocess.run(["make", f"DESTDIR={target_dir}", "install"], cwd=repo_root, env=get_env(), check=True)
    
    # Prune target image
    colors.info(f"OpenSSL: pruning development files and documentation from target...")
    shutil.rmtree(target_dir / "usr" / "include", ignore_errors=True)
    shutil.rmtree(target_dir / "usr" / "lib" / "pkgconfig", ignore_errors=True)
    shutil.rmtree(target_dir / "usr" / "share" / "man", ignore_errors=True)
    shutil.rmtree(target_dir / "usr" / "share" / "doc", ignore_errors=True)
    shutil.rmtree(target_dir / "usr" / "lib" / "cmake", ignore_errors=True)
    
    # Remove static libraries from target to keep it minimal
    lib_dir = target_dir / "usr" / "lib"
    if lib_dir.exists():
        for f in lib_dir.iterdir():
            if f.is_file() and (f.suffix == ".a" or f.suffix == ".la"):
                f.unlink()
