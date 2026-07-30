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
 *
 * DIAGNOSTIC BUILD ONLY: build.sh --memprobe additionally defines NEUTRON_MEMPROBE, which
 * makes memmove/memcpy local wrappers that record WHO CALLS THEM. Nothing below the
 * #ifdef is compiled into the production shim, and build.sh verifies that.
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

#ifdef NEUTRON_MEMPROBE
/* ---- WHO IS DOING ALL THE COPYING? -----------------------------------------
 *
 * A profile of Premiere's timeline zoom puts `ucrtbase!memmove` at ~18% of the UI thread
 * even after the WIC read-through fix removed the GPU round trip's share (~9.5% of the
 * thread, both copies). So ~13.7% of the thread is copying we cannot account for, and it
 * is the single largest known cost.
 *
 * WHY NOT JUST PROFILE IT: perf cannot unwind out of memmove on this workload. Adobe's
 * DLLs are MSVC-built without frame pointers, so 84% of samples yield <=3 frames and the
 * frames past the leaf are stack garbage (`cccccccc00000004`). Hardware LBR unwinds
 * native ELF perfectly (verified: 6/6 frames of a known chain) but truncates to one
 * caller on Wine PE code. So the call stack is simply not available.
 *
 * WHAT THIS DOES INSTEAD: the shim already replaces one export (_wstat64) with a local
 * implementation, so memmove/memcpy can be replaced the same way -- record
 * __builtin_return_address(0) and the size, then forward. Exact call-site attribution
 * with byte volumes, needing no unwinder at all. This is the same technique that
 * attributed CopyPixels to dvaui.dll when an aggregate counter said the app never read
 * back at all.
 *
 * COST CONTROL: only copies >= NEUTRON_MEMPROBE_MIN bytes (default 4096) are recorded.
 * Small copies are numerous but carry little of the byte volume, and recording them would
 * both distort the measurement and swamp the table.
 *
 * ⛔ DIAGNOSTIC ONLY. This replaces memmove for every process in the prefix. Stage it for
 * a measurement run and revert.
 */
#define MP_SLOTS 512

static LONG64 mp_count[MP_SLOTS], mp_bytes[MP_SLOTS];
static void  *mp_ret[MP_SLOTS];
static LONG64 mp_hist[32];           /* log2 size buckets, all recorded calls */
static LONG64 mp_total_calls, mp_total_bytes, mp_skipped;
static SIZE_T mp_min = 4096;
static LONG    mp_dumping;

typedef void *(__cdecl *memmove_t)(void *, const void *, size_t);
static memmove_t real_memmove, real_memcpy;
static LONG mp_initing;
static int  mp_ready;

/* Used only in the window before the real routines are resolved -- LoadLibrary itself
 * copies memory, so the first calls can arrive while we are still bootstrapping. */
static void *mp_fallback_copy(void *d, const void *s, size_t n)
{
    unsigned char *dp = d; const unsigned char *sp = s;
    if (dp == sp || !n) return d;
    if (dp < sp) { while (n--) *dp++ = *sp++; }
    else { dp += n; sp += n; while (n--) *--dp = *--sp; }
    return d;
}

static void mp_init(void)
{
    HMODULE m;
    char buf[32];

    if (InterlockedCompareExchange(&mp_initing, 1, 0) != 0) return;   /* re-entered */
    m = GetModuleHandleW(L"ucrtbase_orig.dll");
    if (!m) m = LoadLibraryW(L"ucrtbase_orig.dll");
    if (m)
    {
        real_memmove = (memmove_t)(void *)GetProcAddress(m, "memmove");
        real_memcpy  = (memmove_t)(void *)GetProcAddress(m, "memcpy");
    }
    if (GetEnvironmentVariableA("NEUTRON_MEMPROBE_MIN", buf, sizeof(buf)))
    {
        SIZE_T v = 0; const char *p = buf;
        while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        if (v) mp_min = v;
    }
    mp_ready = 1;
}

static void mp_dump(void);

static void mp_record(void *ret, size_t n)
{
    /* Open-addressed by address bits; a full table simply stops recording new sites
     * rather than evicting, so the sites that dominate (which appear first and often)
     * keep accumulating truthfully. */
    unsigned i, h = (unsigned)(((ULONG_PTR)ret >> 4) * 2654435761u) & (MP_SLOTS - 1);
    unsigned bucket = 0;
    size_t v = n;

    while (v >>= 1) ++bucket;
    if (bucket > 31) bucket = 31;
    InterlockedIncrement64(&mp_hist[bucket]);
    InterlockedIncrement64(&mp_total_calls);
    InterlockedExchangeAdd64(&mp_total_bytes, (LONG64)n);
    /* Dump periodically, not only at DLL_PROCESS_DETACH. Relying on teardown means a
     * process that is killed -- or one whose detach never runs -- produces an empty file
     * that reads exactly like "the probe never fired". */
    if (!(mp_total_calls & 0x3ff)) mp_dump();

    for (i = 0; i < MP_SLOTS; i++)
    {
        unsigned k = (h + i) & (MP_SLOTS - 1);
        if (mp_ret[k] == ret) goto hit;
        if (!mp_ret[k])
        {
            if (InterlockedCompareExchangePointer(&mp_ret[k], ret, NULL) != NULL
                    && mp_ret[k] != ret)
                continue;
            goto hit;
        }
        continue;
hit:
        InterlockedIncrement64(&mp_count[k]);
        InterlockedExchangeAdd64(&mp_bytes[k], (LONG64)n);
        return;
    }
    InterlockedIncrement64(&mp_skipped);
}

static void mp_put(HANDLE f, const char *s)
{
    DWORD w, n = 0;
    while (s[n]) n++;
    WriteFile(f, s, n, &w, NULL);
}

static void mp_puthex(HANDLE f, ULONG64 v)
{
    char b[19]; int i = 18;
    b[18] = 0;
    if (!v) { mp_put(f, "0"); return; }
    while (v && i) { int d = (int)(v & 15); b[--i] = (char)(d < 10 ? '0' + d : 'a' + d - 10); v >>= 4; }
    mp_put(f, b + i);
}

static void mp_putdec(HANDLE f, ULONG64 v)
{
    char b[24]; int i = 23;
    b[23] = 0;
    if (!v) { mp_put(f, "0"); return; }
    while (v && i) { b[--i] = (char)('0' + (v % 10)); v /= 10; }
    mp_put(f, b + i);
}

/* Written to NEUTRON_MEMPROBE_LOG (default C:\neutron-memprobe.txt). Addresses are raw
 * runtime addresses -- resolve them against /proc/<pid>/maps with pm-symbolize.py. */
static void mp_dump(void)
{
    char path[512];
    HANDLE f;
    unsigned i;

    if (InterlockedCompareExchange(&mp_dumping, 1, 0) != 0) return;
    /* ONE FILE PER PROCESS. Every process in the prefix loads ucrtbase and dumps on the
     * way out, so a shared filename means the last one to exit -- typically a service
     * that copied nothing -- truncates the real data to zeros. That is indistinguishable
     * from "the probe never fired", and it is exactly what happened the first time. */
    {
        DWORD pid = GetCurrentProcessId();
        const char *base = "C:\\neutron-memprobe";
        char envbuf[400];
        unsigned k = 0;
        if (GetEnvironmentVariableA("NEUTRON_MEMPROBE_LOG", envbuf, sizeof(envbuf)))
            base = envbuf;
        while (base[k] && k < sizeof(path) - 24) { path[k] = base[k]; k++; }
        path[k++] = '-';
        {
            char d[12]; int j = 11;
            d[11] = 0;
            if (!pid) d[--j] = '0';
            while (pid && j) { d[--j] = (char)('0' + (pid % 10)); pid /= 10; }
            while (d[j]) path[k++] = d[j++];
        }
        path[k++] = '.'; path[k++] = 't'; path[k++] = 'x'; path[k++] = 't'; path[k] = 0;
    }
    f = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                    FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) goto done;

    mp_put(f, "# neutron-memprobe: memmove/memcpy callers >= ");
    mp_putdec(f, mp_min);
    mp_put(f, " bytes\n# pid ");
    mp_putdec(f, GetCurrentProcessId());
    mp_put(f, "\ntotal_calls ");   mp_putdec(f, (ULONG64)mp_total_calls);
    mp_put(f, "\ntotal_bytes ");   mp_putdec(f, (ULONG64)mp_total_bytes);
    mp_put(f, "\ntable_overflow "); mp_putdec(f, (ULONG64)mp_skipped);
    mp_put(f, "\n# log2 size histogram: bucket calls\n");
    for (i = 0; i < 32; i++)
        if (mp_hist[i]) { mp_put(f, "hist "); mp_putdec(f, i); mp_put(f, " ");
                          mp_putdec(f, (ULONG64)mp_hist[i]); mp_put(f, "\n"); }
    mp_put(f, "# caller_return_address calls bytes\n");
    for (i = 0; i < MP_SLOTS; i++)
        if (mp_ret[i]) { mp_put(f, "site 0x"); mp_puthex(f, (ULONG64)(ULONG_PTR)mp_ret[i]);
                         mp_put(f, " ");  mp_putdec(f, (ULONG64)mp_count[i]);
                         mp_put(f, " ");  mp_putdec(f, (ULONG64)mp_bytes[i]);
                         mp_put(f, "\n"); }
    CloseHandle(f);
done:
    InterlockedExchange(&mp_dumping, 0);
}

void *__cdecl memmove(void *d, const void *s, size_t n)
{
    if (!mp_ready) mp_init();
    if (n >= mp_min) mp_record(__builtin_return_address(0), n);
    return real_memmove ? real_memmove(d, s, n) : mp_fallback_copy(d, s, n);
}

void *__cdecl memcpy(void *d, const void *s, size_t n)
{
    if (!mp_ready) mp_init();
    if (n >= mp_min) mp_record(__builtin_return_address(0), n);
    return real_memcpy ? real_memcpy(d, s, n) : mp_fallback_copy(d, s, n);
}
#endif /* NEUTRON_MEMPROBE */

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)inst; (void)reserved;
#ifdef NEUTRON_MEMPROBE
    /* Dump on the way out. A probe whose numbers never reach a file is not a
     * measurement -- this project has lost time to exactly that more than once. */
    if (reason == DLL_PROCESS_DETACH) mp_dump();
#else
    (void)reason;
#endif
    return TRUE;
}
