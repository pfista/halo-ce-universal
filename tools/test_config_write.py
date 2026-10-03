"""Exercise the shipped config parser/writer through real files and failed saves.

The fixture compiles port_config.c and tomlc17.c unchanged. Only the platform
logger, SDL file I/O, and an injectable strdup allocation failure are supplied.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Avoid pulling the unrelated Xbox ABI declarations into this native test. */
#define __HALO_LINUX_PLATFORM_H
static void platform_log(const char *format, ...) { (void)format; }

static const char *SDL_GetBasePath(void) { return "./"; }
static void SDL_free(void *value) { free(value); }
static void *SDL_LoadFile(const char *path, size_t *size)
{
    FILE *file = fopen(path, "rb");
    long length;
    char *text = NULL;
    if (!file) return NULL;
    if (!fseek(file, 0, SEEK_END) && (length = ftell(file)) >= 0 &&
        !fseek(file, 0, SEEK_SET)) {
        text = malloc((size_t)length + 1);
        if (text && fread(text, 1, (size_t)length, file) == (size_t)length) {
            text[length] = 0;
            *size = (size_t)length;
        } else { free(text); text = NULL; }
    }
    fclose(file);
    return text;
}
static int SDL_SaveFile(const char *path, const void *text, size_t size)
{
    FILE *file = fopen(path, "wb");
    int written;
    if (!file) return 0;
    written = fwrite(text, 1, size, file) == size;
    return fclose(file) == 0 && written;
}

static int fail_next_string;
static char *fixture_strdup(const char *text)
{
    if (fail_next_string) { fail_next_string = 0; return NULL; }
    return strdup(text);
}
#define strdup fixture_strdup
#include "port_config.c"
#undef strdup

static void expect_file(const char *path, const char *fragment)
{
    size_t size;
    char *text = SDL_LoadFile(path, &size);
    assert(text && strstr(text, fragment));
    toml_result_t parsed = toml_parse(text, (int)size);
    assert(parsed.ok);
    toml_free(parsed);
    free(text);
}

int main(void)
{
    const char *old_mode = config_string("display.mode");
    assert(!strcmp(old_mode, "windowed"));
    assert(config_changes() == 0);
    assert(config_write_boolean("display.fullscreen", 1));
    assert(config_write("display.window_scale", "3"));
    assert(config_write("audio.volume", "0.5"));
    assert(config_write("display.mode", "Main\\Display\""));
    assert(config_changes() == 4);
    assert(config_boolean("display.fullscreen") == 1);
    assert(config_integer("display.window_scale") == 3);
    assert(config_real("audio.volume") == 0.5);
    assert(!strcmp(config_string("display.mode"), "Main\\Display\""));
    assert(!strcmp(old_mode, "windowed")); /* Existing readers retain ownership. */
    expect_file("config.toml", "# Preserve this player's comment\n");
    expect_file("config.toml", "mode = \"Main\\\\Display\\\"\"\n");
    expect_file("config.toml", "window_scale = 3\n");
    expect_file("config.toml", "volume = 0.5\n");

    /* A directory at the destination reliably rejects writes even as root. */
    assert(!rename("config.toml", "config.saved"));
    assert(!mkdir("config.toml", 0700));
    const char *saved_mode = config_string("display.mode");
    assert(!config_write_boolean("display.fullscreen", 0));
    assert(!config_write("display.window_scale", "5"));
    assert(!config_write("audio.volume", "0.25"));
    assert(!config_write("display.mode", "borderless"));
    assert(config_changes() == 4);
    assert(config_boolean("display.fullscreen") == 1);
    assert(config_integer("display.window_scale") == 3);
    assert(config_real("audio.volume") == 0.5);
    assert(config_string("display.mode") == saved_mode);
    assert(!strcmp(saved_mode, "Main\\Display\""));
    assert(!strcmp(old_mode, "windowed"));
    assert(!rmdir("config.toml"));
    assert(!rename("config.saved", "config.toml"));

    fail_next_string = 1;
    assert(!config_write("display.mode", "borderless"));
    assert(!fail_next_string);
    assert(config_string("display.mode") == saved_mode);
    assert(config_changes() == 4);
    expect_file("config.toml", "mode = \"Main\\\\Display\\\"\"\n");

    assert(config_write("display.mode", "borderless"));
    assert(config_changes() == 5);
    assert(!strcmp(config_string("display.mode"), "borderless"));
    assert(!strcmp(saved_mode, "Main\\Display\""));
    assert(!config_write("display.unknown_setting", "1"));
    assert(config_changes() == 5);
    expect_file("config.toml", "mode = \"borderless\"\n");
    puts("Successful saves commit values; failed saves preserve values and change count");
    return 0;
}
'''


class ConfigWriteTests(unittest.TestCase):
    def test_persistence_failure_and_recovery_on_all_file_backends(self):
        for name, defines in (("macos", ["-DHALO_ANDROID", "-DHALO_MACOS"]),
                              ("android", ["-DHALO_ANDROID"]), ("desktop", [])):
            with self.subTest(platform=name), tempfile.TemporaryDirectory(prefix="halo-config-write-") as folder:
                fixture = Path(folder)
                (fixture / "SDL3").mkdir()
                (fixture / "SDL3/SDL.h").write_text("/* File I/O supplied by the fixture. */\n")
                source = fixture / "fixture.c"
                source.write_text(HARNESS)
                binary = fixture / "fixture"
                subprocess.run(["cc", "-std=c11", "-D_DARWIN_C_SOURCE", "-D_DEFAULT_SOURCE", "-pthread",
                                *defines, "-I", str(fixture), "-I", str(ROOT / "port/linux/src"),
                                "-I", str(ROOT / "port/third_party/tomlc17"), str(source),
                                str(ROOT / "port/third_party/tomlc17/tomlc17.c"), "-o", str(binary)], check=True)
                (fixture / "config.toml").write_text(
                    '# Preserve this player\'s comment\n[display]\nmode = "windowed"\n'
                    'fullscreen = false\nwindow_scale = 2\n[audio]\nvolume = 1.0\n')
                environment = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
                subprocess.run([str(binary)], cwd=fixture, env=environment, check=True)


if __name__ == "__main__":
    unittest.main()
