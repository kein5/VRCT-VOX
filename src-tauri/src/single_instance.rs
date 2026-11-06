use std::ffi::OsStr;

pub fn single_instance_enabled(debug_build: bool, config_dir: Option<&OsStr>) -> bool {
    // Worktree builds and tests with separate state must coexist with the installed app.
    // An empty value selects the default state folder, so it is not separate state.
    !debug_build && config_dir.is_none_or(OsStr::is_empty)
}

#[cfg(test)]
mod tests {
    use super::single_instance_enabled;
    use std::ffi::OsStr;

    #[test]
    fn normal_release_uses_single_instance() {
        assert!(single_instance_enabled(false, None));
    }

    #[test]
    fn debug_builds_remain_independent() {
        assert!(!single_instance_enabled(true, None));
        assert!(!single_instance_enabled(
            true,
            Some(OsStr::new("test state"))
        ));
    }

    #[test]
    fn explicit_config_directory_disables_single_instance() {
        assert!(!single_instance_enabled(false, Some(OsStr::new("test state"))));
    }

    #[test]
    fn empty_config_directory_keeps_single_instance() {
        assert!(single_instance_enabled(false, Some(OsStr::new(""))));
    }
}
