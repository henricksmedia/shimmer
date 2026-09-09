// marketing.js — sharing for the posts page.
//
// Three jobs:
//   1. Count the characters in every post, so you know before you paste
//      whether it fits a short-post box (280) or needs a longer home.
//   2. Copy one post, or all of them, to the clipboard.
//   3. Save every post as a plain .txt file.
//
// These pages run both from the app (http://127.0.0.1:7861/static/
// marketing/) and straight off disk. The clipboard API needs a secure
// page, which a file:// page is not, so every copy falls back to the old
// execCommand path. Nothing here talks to the server.

const SHORT_POST_LIMIT = 280;   // the usual short-post box

// The text of one post, with the line breaks the author wrote. innerText
// would fold them; textContent keeps them, because .mk-post-text is
// white-space: pre-wrap.
function postText(card) {
    const body = card.querySelector('.mk-post-text');
    return body ? body.textContent.trim() : '';
}

async function copyText(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (_) { /* fall through to the old way */ }
    // file:// and other non-secure pages.
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, ta.value.length);
        const ok = document.execCommand('copy');
        ta.remove();
        return ok;
    } catch (_) {
        return false;
    }
}

// Say what happened on the button itself, then put it back.
function flash(btn, message, ok = true) {
    if (btn.dataset.busy === '1') return;
    btn.dataset.busy = '1';
    const label = btn.textContent;
    btn.textContent = message;
    btn.classList.toggle('done', ok);
    setTimeout(() => {
        btn.textContent = label;
        btn.classList.remove('done');
        btn.dataset.busy = '0';
    }, 1500);
}

function allPostsText() {
    return Array.from(document.querySelectorAll('.mk-post')).map((card) => {
        const n = card.querySelector('.mk-post-n');
        const title = card.querySelector('h3');
        const head = `${n ? n.textContent.trim() + ' ' : ''}${title ? title.textContent.trim() : ''}`.trim();
        return `${head}\n\n${postText(card)}`;
    }).join('\n\n' + '-'.repeat(60) + '\n\n');
}

function init() {
    // Character counts and per-post copy.
    document.querySelectorAll('.mk-post').forEach((card) => {
        const text = postText(card);
        const count = card.querySelector('.mk-count');
        if (count) {
            const n = text.length;
            count.textContent = n <= SHORT_POST_LIMIT
                ? `${n} characters · fits a 280 box`
                : `${n} characters · too long for a 280 box`;
            count.classList.toggle('over', n > SHORT_POST_LIMIT);
        }
        const btn = card.querySelector('[data-copy-post]');
        if (btn) {
            btn.addEventListener('click', async () => {
                const ok = await copyText(postText(card));
                flash(btn, ok ? 'Copied' : 'Press Ctrl+C', ok);
            });
        }
    });

    // Copy every post at once.
    const all = document.getElementById('copy-all');
    if (all) {
        all.addEventListener('click', async () => {
            const ok = await copyText(allPostsText());
            flash(all, ok ? 'All 10 copied' : 'Copy failed', ok);
        });
    }

    // Save every post as a text file.
    const save = document.getElementById('save-all');
    if (save) {
        save.addEventListener('click', () => {
            const blob = new Blob([allPostsText()], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'shimmer-posts.txt';
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            flash(save, 'Saved');
        });
    }

    // Copy any other block of ready-made copy (the message page).
    document.querySelectorAll('[data-copy-target]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const target = document.getElementById(btn.dataset.copyTarget);
            if (!target) return;
            const ok = await copyText(target.textContent.trim());
            flash(btn, ok ? 'Copied' : 'Press Ctrl+C', ok);
        });
    });
}

document.addEventListener('DOMContentLoaded', init);
