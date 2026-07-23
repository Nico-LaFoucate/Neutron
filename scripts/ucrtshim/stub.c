/* Neutron ucrtbase shim — reproducible source for the proxy that `neutron runtime
 * capture` builds into the runtime bundle and `neutron prefix provision` stages into
 * every Adobe prefix. Loaded via WINEDLLOVERRIDES="ucrtbase=n,b": the api-ms-win-crt-*
 * apisets resolve into ucrtbase.dll = THIS proxy, which forwards ~all exports to MS's
 * real UCRT (renamed ucrtbase_orig.dll by capture) and layers two fixes on top:
 *
 *   1. __CxxFrameHandler4  — MS's UCRT does NOT export it, but the
 *      api-ms-win-crt-private apiset expects it there (CEF / Adobe export path aborts
 *      with "unimplemented function ...__CxxFrameHandler4"). The .def adds the export
 *      forwarded to Wine's builtin vcruntime140_1, which DOES implement it.
 *      (See docs/collider_notes.md §3.)
 *
 *   2. _wstat64  — MS's UCRT _wstat64 runs wcspbrk(path, "?*") as its FIRST operation
 *      and rejects ANY path containing '?' or '*' with errno=ENOENT before touching the
 *      filesystem (a documented UCRT limitation: the _stat family doesn't support
 *      extended-length "\\?\" paths — the '?' in the prefix trips the wildcard check).
 *      Premiere's MainConcept HW-export muxer stats "\\?\"-prefixed temp files to size
 *      the elementary streams; that stat failing made the muxer skip the interleave and
 *      leave a 0-byte MP4. Wine's OWN builtin CRT accepts "\\?\" (it routes through
 *      GetFileAttributesExW). This override strips the "\\?\" drive prefix before
 *      forwarding, making MS's UCRT match Wine's more-permissive behaviour so native
 *      muxing works. (See memory neutron-native-muxing-idea.)
 *
 * Build: scripts/ucrtshim/build.sh <ucrtbase_orig.dll> <out ucrtbase.dll>  (64-bit only —
 * the FH4 proxy and the muxer are 64-bit; syswow64 ships MS's real ucrtbase untouched).
 */
#include <windows.h>

typedef int (__cdecl *wstat_t)(const wchar_t *, void *);
static wstat_t real_wstat;
static int inited;

/* "\\?\X:\.." -> "X:\.." (drive form only; other extended forms pass through). */
static const wchar_t *strip_extended_prefix(const wchar_t *p)
{
    if (p && p[0] == L'\\' && p[1] == L'\\' && p[2] == L'?' && p[3] == L'\\') {
        if (((p[4] >= L'A' && p[4] <= L'Z') || (p[4] >= L'a' && p[4] <= L'z')) && p[5] == L':')
            return p + 4;
    }
    return p;
}

static void init(void)
{
    HMODULE m = GetModuleHandleW(L"ucrtbase_orig.dll");
    if (!m) m = LoadLibraryW(L"ucrtbase_orig.dll");
    if (m) real_wstat = (wstat_t)(void *)GetProcAddress(m, "_wstat64");
    inited = 1;
}

int __cdecl _wstat64(const wchar_t *path, void *st)
{
    if (!inited) init();
    return real_wstat ? real_wstat(strip_extended_prefix(path), st) : -1;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)inst; (void)reason; (void)reserved;
    return TRUE;
}
