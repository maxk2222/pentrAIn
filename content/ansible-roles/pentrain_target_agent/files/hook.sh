# pentrAIn shell telemetry hook — sourced by /etc/bash.bashrc and /etc/zsh/zshrc.
# Logs every executed command as TSV: epoch \t user \t cwd \t command
# plus a result line after each command: R \t exit_code
# telemetried ships these to the platform backend.

_pentrain_log_dir=/var/log/pentrain
mkdir -p "$_pentrain_log_dir" 2>/dev/null || true

# Redirect failures must be silenced by an OUTER redirect — `>> f 2>/dev/null`
# evaluates `>>` first, so a denied file still prints "permission denied" on the
# user's shell. The subshell wraps the whole append in one quiet guard.
_pentrain_log_line() {
    ( printf '%s\t%s\t%s\t%s\n' "$(date +%s.%N)" "${USER:-?}" "${PWD:-?}" \
        "$1" >> "$_pentrain_log_dir/cmd-${USER:-root}.log" ) 2>/dev/null || true
}

_pentrain_log_result() {
    ( printf 'R\t%s\n' "$1" >> "$_pentrain_log_dir/cmd-${USER:-root}.log" ) \
        2>/dev/null || true
}

if [ -n "$BASH_VERSION" ]; then
    _pentrain_log() {
        # skip commands invoked by the hook itself or the daemon
        [ -n "$_PENTRAIN_IN_HOOK" ] && return 0
        _PENTRAIN_IN_HOOK=1
        _pentrain_log_line "$BASH_COMMAND"
        _PENTRAIN_IN_HOOK=
    }
    trap '_pentrain_log' DEBUG
    # PROMPT_COMMAND runs after each command — $? is its exit status.
    _pentrain_precmd() { _pentrain_log_result "$?"; }
    PROMPT_COMMAND="_pentrain_precmd${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
elif [ -n "$ZSH_VERSION" ]; then
    # Kali's default user shell — preexec receives the full command line in $1
    autoload -Uz add-zsh-hook 2>/dev/null
    _pentrain_zsh_preexec() { _pentrain_log_line "$1"; }
    _pentrain_zsh_precmd() { _pentrain_log_result "$?"; }
    if whence add-zsh-hook >/dev/null 2>&1; then
        add-zsh-hook preexec _pentrain_zsh_preexec
        add-zsh-hook precmd _pentrain_zsh_precmd
    else
        preexec() { _pentrain_zsh_preexec "$1"; }
        precmd() { _pentrain_zsh_precmd "$?"; }
    fi
fi
