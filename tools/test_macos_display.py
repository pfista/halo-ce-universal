"""Execute the native display bridge with a controlled SDL window and events.

The production functions are extracted unchanged. No app, desktop window or
game data is opened; failures and launch overrides are deterministic fixtures.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = re.search(r"^\w[\w *]*\b" + name + r"\([^;]*?\)\s*\{", source, re.M)
    if not start:
        raise AssertionError("Missing production function: " + name)
    depth = 0
    for position in range(source.index("{", start.start()), len(source)):
        depth += (source[position] == "{") - (source[position] == "}")
        if not depth:
            return source[start.start():position + 1] + "\n"
    raise AssertionError("Unclosed production function: " + name)


PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "port/macos/native_events.h"
typedef uint64_t SDL_WindowFlags;
typedef uint32_t SDL_DisplayID;
typedef int SDL_Scancode;
typedef struct { int unused; } SDL_DisplayMode;
typedef struct { SDL_WindowFlags flags; int width, height; } SDL_Window;
typedef struct { uint32_t type; struct { int code; void *data1, *data2; } user; } SDL_Event;
enum { SDL_WINDOW_METAL=1, SDL_WINDOW_RESIZABLE=2, SDL_WINDOW_HIGH_PIXEL_DENSITY=4,
       SDL_WINDOW_HIDDEN=8, SDL_WINDOW_FULLSCREEN=16, SDL_EVENT_USER=32, SDL_EVENT_QUIT=64,
       _handle_window=1, HOST_LOG_INFO=4 };
static SDL_Window window;
static SDL_Window *metal_window;
static int metal_window_hidden;
static const char *override;
static SDL_DisplayMode desktop;
static const SDL_DisplayMode *fullscreen_mode;
static SDL_Event event;
static int events, refreshed, fail_mode, fail_fullscreen, fail_size, fail_sync, missing_display;
static const char *SDL_getenv(const char *name) { assert(!strcmp(name,"HALO_WINDOWED")); return override; }
static int SDL_atoi(const char *value) { return atoi(value); }
static SDL_Window *SDL_CreateWindow(const char *title,int width,int height,SDL_WindowFlags flags) {
    assert(title); window=(SDL_Window){flags,width,height}; fullscreen_mode=NULL; return &window;
}
static bool SDL_SyncWindow(SDL_Window *value) { assert(value==&window); return !fail_sync; }
static bool SDL_GetWindowSizeInPixels(SDL_Window *value,int *width,int *height) {
    *width=value->width; *height=value->height; return true;
}
static void host_logf(int priority,const char *format,...) { assert(priority==HOST_LOG_INFO && format); }
static uint32_t handle_new(int type,void *value) { assert(type==_handle_window && value==&window); return 7; }
static SDL_WindowFlags SDL_GetWindowFlags(SDL_Window *value) { return value->flags; }
static const SDL_DisplayMode *SDL_GetWindowFullscreenMode(SDL_Window *value) { assert(value==&window); return fullscreen_mode; }
static SDL_DisplayID SDL_GetDisplayForWindow(SDL_Window *value) { assert(value==&window); return missing_display ? 0 : 1; }
static const SDL_DisplayMode *SDL_GetDesktopDisplayMode(SDL_DisplayID display) { assert(display==1); return &desktop; }
static bool SDL_SetWindowFullscreenMode(SDL_Window *value,const SDL_DisplayMode *mode) {
    assert(value==&window); if(fail_mode) return false; fullscreen_mode=mode; return true;
}
static bool SDL_SetWindowFullscreen(SDL_Window *value,bool enabled) {
    if(fail_fullscreen) return false;
    if(enabled) value->flags|=SDL_WINDOW_FULLSCREEN; else value->flags&=~SDL_WINDOW_FULLSCREEN;
    return true;
}
static bool SDL_SetWindowSize(SDL_Window *value,int width,int height) {
    if(fail_size) return false; value->width=width; value->height=height; return true;
}
static void host_menu_window_changed(void) { refreshed++; }
static bool SDL_PushEvent(SDL_Event *value) { event=*value; events++; return true; }
static const char *SDL_GetScancodeName(SDL_Scancode code) { return code==4 ? "A" : ""; }
static SDL_Scancode SDL_GetScancodeFromName(const char *name) { return !strcmp(name,"A") ? 4 : 0; }
static size_t SDL_strlcpy(char *out,const char *in,size_t size) {
    size_t length=strlen(in); if(size) { size_t count=length<size ? length : size-1; memcpy(out,in,count); out[count]=0; } return length;
}
'''

HARNESS = r'''
int main(void) {
    const SDL_WindowFlags common=SDL_WINDOW_METAL|SDL_WINDOW_RESIZABLE|SDL_WINDOW_HIGH_PIXEL_DENSITY;
    override=NULL;
    assert(host_sdl_create_window("fixture",640,480,0)==7);
    assert(window.flags==common && host_sdl_display_mode()==0);
    assert(host_sdl_create_window("fixture",640,480,SDL_WINDOW_FULLSCREEN)==7);
    assert(host_sdl_display_mode()==1);
    override="1";
    assert(host_sdl_create_window("fixture",640,480,SDL_WINDOW_FULLSCREEN)==7);
    assert(host_sdl_display_mode()==0);
    override="0";
    assert(host_sdl_create_window("fixture",640,480,0)==7);
    assert(host_sdl_display_mode()==1);
    assert(host_sdl_create_window("fixture",640,480,SDL_WINDOW_HIDDEN|SDL_WINDOW_FULLSCREEN)==7);
    assert(window.flags==(common|SDL_WINDOW_HIDDEN));
    assert(host_sdl_apply_display(2,0,0) && host_sdl_display_mode()==0);
    override=NULL;
    host_sdl_create_window("fixture",640,480,0);
    assert(host_sdl_apply_display(2,1280,960));
    assert(host_sdl_display_mode()==2 && fullscreen_mode==&desktop);
    assert(window.width==1280 && window.height==960 && events==0);
    assert(host_sdl_apply_display(-1,1920,1440));
    assert(host_sdl_display_mode()==2 && window.width==1920 && window.height==1440 && events==0);
    assert(host_sdl_apply_display(1,0,0) && host_sdl_display_mode()==1 && !fullscreen_mode);
    assert(host_sdl_apply_display(0,0,0) && host_sdl_display_mode()==0);
    assert(!host_sdl_apply_display(3,0,0));
    assert(!host_sdl_apply_display(-2,0,0));
    assert(!host_sdl_apply_display(0,0,10));
    assert(!host_sdl_apply_display(0,-1,10));
    assert(host_sdl_set_fullscreen(1) && events==1 && host_sdl_display_mode()==1);
    assert(event.type==SDL_EVENT_USER && event.user.code==HALO_MACOS_DISPLAY_BORDERLESS);
    assert(!event.user.data1 && !event.user.data2);
    assert(host_sdl_set_fullscreen(0) && events==2 && host_sdl_display_mode()==0);
    assert(event.user.code==HALO_MACOS_DISPLAY_WINDOWED && !event.user.data1 && !event.user.data2);
    fail_mode=1;
    assert(!host_sdl_set_fullscreen(1) && events==2 && host_sdl_display_mode()==0);
    fail_mode=0; fail_fullscreen=1;
    assert(!host_sdl_set_fullscreen(1) && events==2);
    fail_fullscreen=0; fail_sync=1;
    assert(!host_sdl_set_fullscreen(1) && events==2);
    fail_sync=0; fail_size=1;
    assert(!host_sdl_apply_display(-1,640,480) && events==2);
    fail_size=0; missing_display=1;
    assert(!host_sdl_apply_display(2,0,0) && events==2);
    missing_display=0;
    host_sdl_request_quit();
    assert(events==3 && event.type==SDL_EVENT_QUIT && !event.user.data1 && !event.user.data2);
    metal_window=NULL;
    assert(host_sdl_display_mode()==0 && !host_sdl_apply_display(0,0,0));
    char name[3]={'x','x','x'};
    host_sdl_scancode_name(4,name,2); assert(!strcmp(name,"A") && name[2]=='x');
    host_sdl_scancode_name(4,name,1); assert(name[0]==0 && name[2]=='x');
    host_sdl_scancode_name(-1,name,sizeof(name)); assert(!name[0]);
    assert(host_sdl_scancode_from_name("A")==4 && host_sdl_scancode_from_name("unknown")==0);
    return 0;
}
'''


class MacDisplayTests(unittest.TestCase):
    def test_native_and_pc_display_actions_share_modes_without_feedback_events(self):
        source = (ROOT / "port/macos/host/host_sdl.c").read_text()
        names = ("host_sdl_create_window", "host_sdl_is_fullscreen", "host_sdl_display_mode",
                 "host_sdl_apply_display", "host_sdl_set_fullscreen", "host_sdl_request_quit",
                 "host_sdl_scancode_name", "host_sdl_scancode_from_name")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "display.c"
            fixture.write_text(PREFIX + "\n".join(function(source, name) for name in names) + HARNESS)
            executable = Path(temporary) / "display"
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O1",
                            "-fsanitize=address,undefined", "-I", str(ROOT), str(fixture),
                            "-o", str(executable)], check=True, capture_output=True, text=True)
            subprocess.run([str(executable)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
