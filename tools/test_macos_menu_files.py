"""Exercise desktop XML discovery through the real Mac directory bridge."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_macos_pointer import function

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "posix.h"
struct menu_file_embedded {const char *path; const char *data; unsigned long size;};
static const struct menu_file_embedded menu_files_embedded[]={
    {"main.xml","builtin",7}, {"ce/base.xml","base",4}
};
static const unsigned menu_files_embedded_count=2;
static const char *root;
static void config_folder(char *text,size_t size) {snprintf(text,size,"%s/",root);}
static void platform_log(const char *text,...) {(void)text;}
typedef char XML_Char;
struct reader {int errors;};
static void reader_error(struct reader *reader,const char *message,...) {(void)message; reader->errors++;}
'''

CHECKS = r'''
static void check_file(const char *name,const char *text,int loaded) {
    long index=file_find(name); assert(index>=0);
    assert(files[index].size==strlen(text));
    assert(!memcmp(files[index].data,text,strlen(text)));
    assert(files[index].loaded==loaded);
}
static void clear_files(void) {
    for (long i=0;i<file_count;i++) {
        free(files[i].path); if (files[i].loaded) free((void *)files[i].data);
    }
    free(files); files=NULL; file_count=0;
}
int main(int argc,char **argv) {
    assert(argc==2); root=argv[1];
    struct reader reader={0};
    const XML_Char *desktop[]={"name","item","platform","desktop",NULL};
    const XML_Char *android[]={"platform","android",NULL};
    const XML_Char *both[]={"name","item",NULL};
    const XML_Char *invalid[]={"platform","invalid",NULL};
#ifdef HALO_MACOS
    assert(for_this_platform(&reader,desktop));
    assert(!for_this_platform(&reader,android));
#else
    assert(!for_this_platform(&reader,desktop));
    assert(for_this_platform(&reader,android));
#endif
    assert(for_this_platform(&reader,both) && reader.errors==0);
    assert(for_this_platform(&reader,invalid) && reader.errors==1);
    /* More iterations than the bridge's handle pool: each shallow scan must
       close its directories and free each overridden/local file exactly once. */
    for (int repeat=0;repeat<70;repeat++) {
        files_gather();
        check_file("main.xml","builtin",0);
        check_file("ce/base.xml","overridden",1);
#ifdef HALO_MACOS
        assert(file_count==4);
        check_file("extra.xml","root-local",1);
        check_file("ce/added.xml","nested-local",1);
#else
        assert(file_count==2);
#endif
        assert(file_find("readme.txt")==-1);
        assert(file_find("upper.XML")==-1);
        assert(file_find("ce/deeper/hidden.xml")==-1);
        assert(file_find("broken.xml")==-1);
        clear_files();
    }
    root="/a/nonexistent/halo-menu-fixture";
    files_gather(); assert(file_count==2);
    check_file("main.xml","builtin",0); check_file("ce/base.xml","base",0);
    clear_files();
    return 0;
}
'''


class MacMenuFiles(unittest.TestCase):
    def run_fixture(self, macos):
        compiler = shutil.which("clang")
        if not compiler:
            self.skipTest("clang is required")
        source = (ROOT / "port/linux/src/menu_files.c").read_text()
        start = source.index("struct menu_file\n")
        end = source.index("/* a file's data", start)
        fixture = (PREFIX + source[start:end] +
                   function(source, "static int for_this_platform(") + CHECKS)
        with tempfile.TemporaryDirectory(prefix="halo-menu-files-") as directory:
            temp = Path(directory)
            menus = temp / "menus"
            (menus / "ce/deeper").mkdir(parents=True)
            entries = {
                "ce/base.xml": "overridden", "extra.xml": "root-local",
                "ce/added.xml": "nested-local", "ce/deeper/hidden.xml": "too-deep",
                "readme.txt": "ignored", "upper.XML": "ignored-case",
            }
            for name, data in entries.items():
                (menus / name).write_text(data)
            (menus / "broken.xml").symlink_to(menus / "absent.xml")
            before = {name: (menus / name).read_bytes() for name in entries}
            (temp / "menus.c").write_text(fixture)
            command = [compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                       "-DHALO_ANDROID=1", "-I", str(ROOT / "port/linux/src")]
            if macos:
                command += ["-DHALO_MACOS=1", str(ROOT / "port/macos/host/posix_files.c")]
            result = subprocess.run(command + [str(temp / "menus.c"), "-pthread", "-o", str(temp / "test")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(temp / "test"), str(temp)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, {name: (menus / name).read_bytes() for name in entries})

    def test_macos_uses_desktop_elements_and_shallow_custom_xml(self):
        self.run_fixture(True)

    def test_android_keeps_platform_selection_and_embedded_override_behavior(self):
        self.run_fixture(False)


if __name__ == "__main__":
    unittest.main()
