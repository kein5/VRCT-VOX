//! Which URLs the app may open in the user's browser (second security audit SEC-02).
//!
//! Capabilities are combined per window, so one broad grant such as `opener:default` would undo
//! the list in vrct_capability.json. Only the main window may open URLs, and only those the list
//! allows. The opener plugin matches the scope with `glob::Pattern::matches`, denials first
//! (tauri-plugin-opener 2.7.2, src/scope.rs); these tests use the same matcher.
use serde_json::Value;

const CAPABILITIES: [(&str, &str); 4] = [
    ("default.json", include_str!("../capabilities/default.json")),
    ("vrct_capability.json", include_str!("../capabilities/vrct_capability.json")),
    ("quick-chat.json", include_str!("../capabilities/quick-chat.json")),
    ("caption-overlay.json", include_str!("../capabilities/caption-overlay.json")),
];

fn parse(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}

fn identifier(permission: &Value) -> &str {
    permission.as_str().or_else(|| permission["identifier"].as_str()).unwrap()
}

fn patterns(entry: &Value, key: &str) -> Vec<glob::Pattern> {
    entry[key].as_array().map_or(vec![], |items| {
        items.iter().map(|item| glob::Pattern::new(item["url"].as_str().unwrap()).unwrap()).collect()
    })
}

fn scope() -> (Vec<glob::Pattern>, Vec<glob::Pattern>) {
    let capability = parse(CAPABILITIES[1].1);
    let entry = capability["permissions"].as_array().unwrap().iter()
        .find(|permission| identifier(permission) == "opener:allow-open-url").expect("the URL scope");
    (patterns(entry, "allow"), patterns(entry, "deny"))
}

fn allowed(url: &str) -> bool {
    let (allow, deny) = scope();
    !deny.iter().any(|pattern| pattern.matches(url)) && allow.iter().any(|pattern| pattern.matches(url))
}

#[test]
fn only_the_main_window_may_open_urls_and_only_through_the_list() {
    // Every file in the folder is checked (a new one must be added to CAPABILITIES).
    let folder = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("capabilities");
    let files = std::fs::read_dir(folder).unwrap().filter_map(|entry| entry.ok())
        .filter(|entry| entry.path().extension().is_some_and(|extension| extension == "json")).count();
    assert_eq!(files, CAPABILITIES.len());
    for (name, text) in CAPABILITIES {
        let capability = parse(text);
        let windows: Vec<&str> = capability["windows"].as_array().unwrap().iter().map(|w| w.as_str().unwrap()).collect();
        for permission in capability["permissions"].as_array().unwrap() {
            let id = identifier(permission);
            if !id.starts_with("opener:") {
                continue;
            }
            assert_eq!(id, "opener:allow-open-url", "{name}: {id} grants more than the listed URLs");
            assert_eq!(windows, ["main"], "{name}: only the main window opens links");
            assert!(permission["allow"].as_array().is_some_and(|list| !list.is_empty()), "{name}: no URL list");
        }
    }
}

#[test]
fn the_links_the_app_shows_can_be_opened() {
    for url in [
        "https://kein5.github.io/VRCT-VOX/en/guide/first-setup",
        "https://kein5.github.io/VRCT-VOX/ja/guide/custom-models#seed-vc",
        "https://github.com/kein5/VRCT-VOX",
        "https://github.com/kein5/VRCT-VOX/releases",
        "https://github.com/kein5/VRCT-VOX/blob/main/NOTICE.md",
        "https://misyaguziya.github.io/VRCT-Docs/",
        "https://misyaguziya.github.io/VRCT-Docs/ja",
        "https://github.com/misyaguziya",
        "https://github.com/misyaguziya/VRCT",
        "https://twitter.com/misya_ai",
        "https://www.deepl.com/ja/your-account/keys",
        "https://console.deepgram.com/",
        "https://huggingface.co/facebook/m2m100_418M",
        "https://huggingface.co/sakasegawa/silero-vad-GGUF/blob/0123abc/LICENSE",
        "https://huggingface.co/Plachta/Seed-VC/tree/main?x=1",
        "https://creativecommons.org/licenses/by-nc/4.0/",
        "https://www.apache.org/licenses/LICENSE-2.0",
        "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8/LICENSE",
        "https://github.com/pytorch/pytorch/blob/main/LICENSE",
        "https://docs.nvidia.com/cuda/eula/index.html",
    ] {
        assert!(allowed(url), "{url} should open");
    }
}

#[test]
fn other_urls_and_other_schemes_are_refused() {
    for url in [
        "https://example.com/",
        "http://github.com/kein5/VRCT-VOX",
        "https://github.com/someone/else",
        "https://github.com/kein5/other-repository",
        "https://github.com/kein5/VRCT-VOX/../../someone/else",
        "https://github.com/kein5/VRCT-VOX/%2e%2e/%2E%2E/someone/else",
        "https://github.com/kein5/VRCT-VOX/..",
        "https://github.com/kein5/VRCT-VOX\\..\\..\\someone",
        "https://github.com/kein5/VRCT-VOX/%5c..",
        "https://huggingface.co.example.com/",
        "https://huggingface.co@example.com/",
        "https://twitter.com/someone_else",
        "https://creativecommons.org/licenses/by/4.0/../../",
        "file:///C:/Windows/System32/calc.exe",
        "mailto:someone@example.com",
        "tel:+810000000000",
        "ms-settings:privacy",
        "javascript:alert(1)",
    ] {
        assert!(!allowed(url), "{url} should be refused");
    }
}
