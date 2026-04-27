# ~/.profile — sourced by login shells. Delegate to .bashrc so the
# GitHub Actions env is available in both interactive and scripted
# shells.
if [ -n "$BASH_VERSION" ] && [ -f "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi
