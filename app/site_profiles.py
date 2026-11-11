"""Persistent WebView2 profiles for Douyin and Xiaohongshu.

Each site keeps its own user-data folder under the data directory. pywebview uses one
process-wide folder for the main window, so login and page capture create a separate
WebView2 environment and export cookies through CookieManager. Chrome and Edge cookie
databases are never read. A Netscape file uploaded on a card remains the per-batch fallback.
"""
import json
import logging
import shutil
import threading
import time
from pathlib import Path

LOGGER = logging.getLogger("media-operator")
LOCK = threading.RLock()
ACTIVE = set()
SITES = {
    "douyin": {
        "label": "抖音",
        "home": "https://www.douyin.com/",
        "domains": ("douyin.com", "iesdouyin.com"),
        "session_names": {"sessionid", "sessionid_ss", "sid_guard", "uid_tt", "sid_tt"},
    },
    "xiaohongshu": {
        "label": "小红书",
        "home": "https://www.xiaohongshu.com/",
        "domains": ("xiaohongshu.com",),
        "session_names": {"web_session"},
    },
}
NAMES = {"抖音": "douyin", "小红书": "xiaohongshu"}


def canonical_site(value):
    key = NAMES.get(value, value)
    if key not in SITES:
        raise ValueError("仅支持登录抖音或小红书")
    return key


def profile_dir(site):
    from app import main as media

    return Path(media.DATA_DIR) / "site-profiles" / canonical_site(site)


def user_data_dir(site):
    return profile_dir(site) / "webview"


def cookies_path(site):
    return profile_dir(site) / "cookies.txt"


def site_for_url(url):
    from app.sites.resolve import platform_of

    label = platform_of(url)[0]
    return {"抖音": "douyin", "小红书": "xiaohongshu"}.get(label)


def status(site):
    key = canonical_site(site)
    folder = profile_dir(key)
    logged_in = False
    meta = folder / "profile.json"
    if meta.is_file() and cookies_path(key).is_file():
        try:
            logged_in = bool(json.loads(meta.read_text(encoding="utf-8")).get("logged_in"))
        except (OSError, ValueError):
            logged_in = False
    with LOCK:
        logging_in = key in ACTIVE
    return {"site": key, "platform": SITES[key]["label"], "logged_in": logged_in, "logging_in": logging_in}


def status_all():
    return {"sites": [status(key) for key in SITES]}


def _write_meta(site, logged_in):
    from app import main as media

    folder = profile_dir(site)
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "profile.json.tmp"
    temporary.write_text(json.dumps({"logged_in": bool(logged_in), "saved_at": media.now_iso()}, ensure_ascii=False),
                         encoding="utf-8")
    temporary.replace(folder / "profile.json")


def write_cookies(site, lines, logged_in):
    key = canonical_site(site)
    folder = profile_dir(key)
    folder.mkdir(parents=True, exist_ok=True)
    path = cookies_path(key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)
    _write_meta(key, logged_in)
    if logged_in:
        _clear_probes(SITES[key]["label"])
    return status(key)


def cookie_rows(url):
    key = site_for_url(url)
    if not key or not status(key)["logged_in"]:
        return None
    try:
        text = cookies_path(key).read_text(encoding="utf-8")
    except OSError:
        return None
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("# Netscape") or line.startswith("# HTTP Cookie"):
            continue
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        rows.append(line)
    return "\n".join(rows) if rows else None


def _clear_probes(label):
    from app import desktop_sources

    desktop_sources.clear_site_probes(label)


def _retire(folder):
    target = folder / "webview"
    if not target.exists():
        return
    trash = folder / f"webview-removed-{int(time.time())}"
    try:
        target.rename(trash)
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        return
    shutil.rmtree(trash, ignore_errors=True)


def logout(site):
    key = canonical_site(site)
    folder = profile_dir(key)
    for name in ("cookies.txt", "cookies.tmp", "profile.json"):
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            pass
    _retire(folder)
    _clear_probes(SITES[key]["label"])
    return status(key)


def gui_host():
    try:
        from webview.platforms.winforms import BrowserView
    except Exception as error:
        raise RuntimeError("请从 Media Operator 桌面窗口登录") from error
    host = next(iter(BrowserView.instances.values()), None)
    if host is None:
        raise RuntimeError("请从 Media Operator 桌面窗口登录")
    return host


def _session_cookie(site, name):
    lowered = name.lower()
    return name in SITES[site]["session_names"] or "session" in lowered


def _matches(site, domain):
    host = domain.removeprefix("#HttpOnly_").lstrip(".").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in SITES[site]["domains"])


def _netscape(cookie):
    domain = cookie["domain"]
    if not domain or "\t" in cookie["name"] or "\t" in cookie["value"] or "\n" in cookie["value"]:
        return ""
    prefix = "#HttpOnly_" if cookie["httponly"] else ""
    flag = "TRUE" if str(domain).startswith(".") else "FALSE"
    secure = "TRUE" if cookie["secure"] else "FALSE"
    path = cookie["path"] or "/"
    return f"{prefix}{domain}\t{flag}\t{path}\t{secure}\t{cookie['expires']}\t{cookie['name']}\t{cookie['value']}"


def _snapshot_cookie(cookie):
    from System import DateTime, DateTimeKind

    domain = str(cookie.Domain or "")
    name = str(cookie.Name or "")
    value = str(cookie.Value or "")
    if not name:
        return None
    expires = cookie.Expires
    stamp = 0
    try:
        if expires.Year >= 1971:
            epoch = DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)
            stamp = max(0, int((expires.ToUniversalTime() - epoch).TotalSeconds))
    except Exception:
        stamp = 0
    return {
        "name": name, "value": value, "domain": domain, "path": str(cookie.Path or "/"),
        "secure": bool(cookie.IsSecure), "httponly": bool(cookie.IsHttpOnly), "expires": stamp,
    }


def _build(site, hidden, setup):
    import webview.platforms.edgechromium  # noqa: F401
    from System import Action
    from System.Drawing import Size
    from System.Threading.Tasks import Task, TaskScheduler
    import System.Windows.Forms as WinForms
    from Microsoft.Web.WebView2.Core import CoreWebView2Environment
    from Microsoft.Web.WebView2.WinForms import WebView2

    spec = SITES[site]
    folder = user_data_dir(site)
    folder.mkdir(parents=True, exist_ok=True)
    form = WinForms.Form()
    form.Text = spec["label"] if hidden else f"登录{spec['label']}"
    form.ClientSize = Size(980, 720)
    form.StartPosition = WinForms.FormStartPosition.CenterScreen
    view = WebView2()
    view.Dock = WinForms.DockStyle.Fill
    button = None
    if hidden:
        form.Text = f"正在读取{spec['label']}"
    else:
        button = WinForms.Button()
        button.Text = "完成登录"
        button.Dock = WinForms.DockStyle.Bottom
        button.Height = 42
        form.Controls.Add(button)
    form.Controls.Add(view)
    scheduler = TaskScheduler.FromCurrentSynchronizationContext()
    state = {"ready": False}

    def environment_ready(task):
        if task.IsFaulted:
            setup(None, form, "无法创建站点浏览器环境")
            return
        view.EnsureCoreWebView2Async(task.Result)

    def initialized(sender, args):
        if not args.IsSuccess:
            setup(None, form, "WebView2 初始化失败")
            return
        core = sender.CoreWebView2

        def new_window(origin, event):
            event.set_Handled(True)
            core.Navigate(str(event.get_Uri()))

        def block_download(origin, event):
            event.Cancel = True

        core.NewWindowRequested += new_window
        core.DownloadStarting += block_download
        state["ready"] = True
        setup(view, form, "")

    view.CoreWebView2InitializationCompleted += initialized
    if button is not None:
        def finish_click(sender, args):
            form.Close()

        button.Click += finish_click
    CoreWebView2Environment.CreateAsync(None, str(folder), None).ContinueWith(
        Action[Task[CoreWebView2Environment]](environment_ready), scheduler,
    )
    form.Show()
    return form, view, scheduler, state


def open_login(site):
    from System import Action, Func, Object
    from System.Collections.Generic import List
    from System.Threading.Tasks import Task
    from Microsoft.Web.WebView2.Core import CoreWebView2Cookie

    host = gui_host()
    key = canonical_site(site)
    holder = {}

    def start():
        def setup(view, form, error):
            if error or view is None:
                with LOCK:
                    ACTIVE.discard(key)
                if not form.IsDisposed:
                    form.BeginInvoke(Action(form.Dispose))
                return
            core = view.CoreWebView2
            phase = {"value": "open"}

            def snapshot(task):
                rows = []
                try:
                    for cookie in task.Result:
                        item = _snapshot_cookie(cookie)
                        if item and _matches(key, item["domain"]):
                            line = _netscape(item)
                            if line:
                                rows.append((item["name"], line))
                except Exception:
                    LOGGER.exception("Cookie export failed")
                    rows = []
                try:
                    if any(_session_cookie(key, name) for name, _ in rows):
                        write_cookies(key, [line for _, line in rows], True)
                finally:
                    phase["value"] = "done"
                    with LOCK:
                        ACTIVE.discard(key)
                    if not form.IsDisposed:
                        form.BeginInvoke(Action(form.Dispose))

            def closing(sender, args):
                if phase["value"] != "open":
                    return
                args.Cancel = True
                phase["value"] = "exporting"
                try:
                    core.CookieManager.GetCookiesAsync(SITES[key]["home"]).ContinueWith(
                        Action[Task[List[CoreWebView2Cookie]]](snapshot), holder["scheduler"],
                    )
                except Exception:
                    LOGGER.exception("CookieManager is unavailable")
                    phase["value"] = "done"
                    with LOCK:
                        ACTIVE.discard(key)
                    form.BeginInvoke(Action(form.Dispose))

            form.FormClosing += closing
            core.Navigate(SITES[key]["home"])

        form, view, scheduler, _ = _build(key, False, setup)
        holder["form"] = form
        holder["scheduler"] = scheduler
        return True

    host.Invoke(Func[Object](start))


def start_login(site):
    key = canonical_site(site)
    with LOCK:
        if key in ACTIVE:
            raise RuntimeError("登录窗口已打开")
        ACTIVE.add(key)
    try:
        open_login(key)
    except Exception as error:
        with LOCK:
            ACTIVE.discard(key)
        if isinstance(error, RuntimeError):
            raise
        LOGGER.exception("Site login failed")
        raise RuntimeError("无法打开登录窗口。可改用 Netscape Cookie 文件。") from error
    return status(key)


def can_capture(url):
    key = site_for_url(url)
    if not key or not status(key)["logged_in"]:
        return False
    try:
        gui_host()
    except RuntimeError:
        return False
    return True


def capture(url):
    """Open the canonical page in the site's logged-in WebView and collect HTML plus media URLs."""
    from System import Action, Func, Object, String
    from System.Threading.Tasks import Task
    from app import main as media
    from app.source_network import public_target

    key = site_for_url(url)
    if not key or not status(key)["logged_in"]:
        raise RuntimeError("尚未登录")
    public_target(url, media.online_media_proxy(url))
    host = gui_host()
    done = threading.Event()
    found = {"url": url, "html": "", "media_urls": [], "webview": False}
    holder = {}

    def start():
        media_urls = []

        def setup(view, form, error):
            if error or view is None:
                done.set()
                if form is not None and not form.IsDisposed:
                    form.BeginInvoke(Action(form.Dispose))
                return
            core = view.CoreWebView2
            token = {"value": 0}
            started = time.monotonic()
            player_script = r"""
                (() => {
                  const parts = [];
                  for (const node of document.scripts) {
                    const text = node.textContent || '';
                    if (node.id === 'RENDER_DATA' || /playAddr|play_addr|playApi|aweme_id|awemeId|RENDER_DATA/.test(text))
                      parts.push(text.slice(0, 200000));
                    else if (/__INITIAL_STATE__|noteDetailMap/.test(text))
                      parts.push(text.slice(0, 400000));
                  }
                  const video = document.querySelector('video');
                  const videos = [...document.querySelectorAll('video')].map((node) => node.currentSrc || node.src || '').filter(Boolean).slice(0, 8);
                  const entries = performance.getEntriesByType('resource').map((entry) => entry.name);
                  const videoEntries = entries.filter((name) => /douyinvod|\.mp4|aweme\/v1\/play|mime_type=video|playApi|xhscdn|sns-video/i.test(name));
                  const audioEntries = entries.filter((name) => /mime_type=audio|\.m4a|audio_mp4|media-audio/i.test(name));
                  return {
                    text: parts.join('\n'),
                    src: video ? (video.currentSrc || video.src || '') : '',
                    videos: videos,
                    duration: video && isFinite(video.duration) ? video.duration : 0,
                    entries: videoEntries.slice(-30),
                    audio: audioEntries.slice(-10)
                  };
                })()
            """

            def finish(text, urls, duration, audio_urls=None):
                if done.is_set():
                    return
                found["html"] = text if isinstance(text, str) else ""
                found["media_urls"] = list(urls)
                found["audio_urls"] = list(audio_urls or [])
                found["duration"] = duration
                found["webview"] = True
                try:
                    found["url"] = str(view.Source) or url
                except Exception:
                    found["url"] = url
                done.set()
                if not form.IsDisposed:
                    form.BeginInvoke(Action(form.Dispose))

            def grab(task):
                if done.is_set():
                    return
                raw = task.Result or ""
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    payload = raw
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (TypeError, ValueError):
                        payload = {"text": payload}
                if not isinstance(payload, dict):
                    payload = {"text": str(payload or "")}
                text = payload.get("text") or ""
                if key == "xiaohongshu":
                    from app.sites.resolve import xhs_capture_ready
                    videos = []
                    for item in [payload.get("src"), *(payload.get("videos") or [])]:
                        if isinstance(item, str) and item.startswith("http") and item not in videos:
                            videos.append(item)
                    sniffed = list(media_urls)
                    for item in payload.get("entries") or []:
                        if isinstance(item, str) and item.startswith("http") and item not in sniffed:
                            sniffed.append(item)
                    if xhs_capture_ready(text, sniffed, videos) or time.monotonic() - started >= 20:
                        finish(text, [*videos, *sniffed], payload.get("duration") or None)
                        return
                    threading.Thread(target=lambda: (time.sleep(0.8), schedule()), daemon=True).start()
                    return
                if key != "douyin":
                    finish(text, media_urls, None)
                    return
                from app.sites.resolve import classify, order_player_urls, player_feature
                current = url
                try:
                    current = str(view.Source) or url
                except Exception:
                    pass
                aweme = classify(current).get("aweme_id") or ""
                feature = player_feature(text, aweme) or {}
                urls = order_player_urls(feature.get("url") or "", payload.get("src") or "", payload.get("entries") or [])
                audio_urls = []
                if feature.get("audio_url"):
                    audio_urls.append(feature["audio_url"])
                for name in payload.get("audio") or []:
                    if isinstance(name, str) and name.startswith("http") and name not in audio_urls:
                        audio_urls.append(name)
                duration = payload.get("duration") or feature.get("duration") or 0
                try:
                    duration = float(duration or 0)
                except (TypeError, ValueError):
                    duration = 0
                ready = bool(urls) and (duration >= 30 or (feature.get("duration") or 0) >= 30)
                if ready or (urls and time.monotonic() - started >= 8):
                    finish(text, urls, duration or feature.get("duration"), audio_urls)
                    return
                if time.monotonic() - started < 8:
                    threading.Thread(target=lambda: (time.sleep(1), schedule()), daemon=True).start()
                    return
                finish(text, urls, duration or None, audio_urls)

            def schedule():
                if done.is_set() or form.IsDisposed:
                    return
                try:
                    host.BeginInvoke(Action(read_player))
                except Exception:
                    done.set()

            def read_player():
                if done.is_set() or form.IsDisposed:
                    return
                core.ExecuteScriptAsync(player_script).ContinueWith(
                    Action[Task[String]](grab), holder["scheduler"],
                )

            def observe(sender, args):
                if key == "douyin":
                    return
                try:
                    address = str(args.Request.Uri)
                except Exception:
                    return
                lowered = address.lower()
                if lowered.startswith("http") and any(token_text in lowered for token_text in (
                    ".mp4", ".m3u8", "mime_type=video", "/aweme/v1/play",
                )) and address not in media_urls and len(media_urls) < 30:
                    media_urls.append(address)

            def navigated(sender, args):
                if not args.IsSuccess:
                    return
                token["value"] += 1
                expected = token["value"]

                def later():
                    time.sleep(1.2 if key != "douyin" else 0.4)
                    if done.is_set() or token["value"] != expected or form.IsDisposed:
                        return
                    schedule()

                threading.Thread(target=later, daemon=True).start()

            def closing(sender, args):
                if not done.is_set():
                    found["media_urls"] = [] if key == "douyin" else list(media_urls)
                    done.set()

            core.WebResourceResponseReceived += observe
            view.NavigationCompleted += navigated
            form.FormClosing += closing
            core.Navigate(url)

        form, view, scheduler, _ = _build(key, True, setup)
        holder["form"] = form
        holder["scheduler"] = scheduler
        return True

    host.Invoke(Func[Object](start))
    if not done.wait(12 if key == "douyin" else 40):
        form = holder.get("form")
        if form is not None:
            try:
                host.Invoke(Func[Object](lambda: form.Dispose() if not form.IsDisposed else True))
            except Exception:
                pass
        raise RuntimeError("登录页面读取超时")
    if not found["webview"] and not found["html"]:
        raise RuntimeError("没有读到登录后的页面")
    return found
