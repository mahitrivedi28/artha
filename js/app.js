/* ============================================================
   ARTHA — shared frontend behaviour
   Note: this is a FRONTEND-ONLY prototype. Lockouts, OTP checks,
   and "encryption" shown here are simulated for UI/UX purposes.
   Real security (hashing, CSRF, encryption) must live server-side.
   ============================================================ */

// ---------- Modals ----------
function openModal(id){ document.getElementById(id)?.classList.add('open'); }
function closeModal(id){ document.getElementById(id)?.classList.remove('open'); }
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(m => m.classList.remove('open'));
  }
});

// ---------- Toasts ----------
function showToast(message, type = 'success') {
  let stack = document.querySelector('.toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'toast-stack';
    document.body.appendChild(stack);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === 'success' ? '✅' : '⚠️'}</span><span>${message}</span>`;
  stack.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity .3s'; }, 2600);
  setTimeout(() => toast.remove(), 3000);
}

// ---------- Password show/hide ----------
function togglePassword(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.textContent = show ? 'Hide' : 'Show';
}

// ---------- Password strength meter ----------
function scorePassword(pw) {
  let score = 0;
  if (!pw) return 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return Math.min(score, 4);
}
function initStrengthMeter(inputId, meterId, labelId) {
  const input = document.getElementById(inputId);
  const bars = document.querySelectorAll(`#${meterId} .strength-bar`);
  const label = document.getElementById(labelId);
  const labels = ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong'];
  const colors = ['#B0503F', '#B0503F', '#D9B564', '#3FA796', '#2F6D63'];
  if (!input) return;
  input.addEventListener('input', () => {
    const score = scorePassword(input.value);
    bars.forEach((bar, i) => {
      bar.style.background = i < score ? colors[score] : 'var(--card-line)';
    });
    if (label) {
      label.textContent = input.value ? labels[score] : '';
      label.style.color = colors[score] || 'var(--text-muted)';
    }
  });
}

// ---------- OTP input group ----------
function initOtpGroup(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const boxes = [...container.querySelectorAll('.otp-box')];
  boxes.forEach((box, i) => {
    box.addEventListener('input', () => {
      box.value = box.value.replace(/[^0-9]/g, '').slice(0, 1);
      if (box.value && boxes[i + 1]) boxes[i + 1].focus();
    });
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !box.value && boxes[i - 1]) boxes[i - 1].focus();
    });
    box.addEventListener('paste', (e) => {
      e.preventDefault();
      const digits = (e.clipboardData.getData('text') || '').replace(/[^0-9]/g, '').split('');
      boxes.forEach((b, idx) => { b.value = digits[idx] || ''; });
      (boxes[Math.min(digits.length, boxes.length) - 1] || boxes[0]).focus();
    });
  });
}

// ---------- Resend OTP countdown ----------
function initResendTimer(buttonId, seconds = 30) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  let remaining = seconds;
  btn.disabled = true;
  const original = btn.dataset.label || 'Resend code';
  const tick = () => {
    if (remaining <= 0) {
      btn.disabled = false;
      btn.textContent = original;
      return;
    }
    btn.textContent = `${original} (${remaining}s)`;
    remaining--;
    setTimeout(tick, 1000);
  };
  tick();
}

// ---------- Login lockout simulation ----------
// Tracks failed attempts client-side (sessionStorage-free — pure JS var,
// resets on refresh) purely to demonstrate the UX. Real lockout state
// must be enforced server-side, keyed by account + IP.
const loginState = { attempts: 0, maxAttempts: 5, lockedUntil: null };

function simulateLoginAttempt(success) {
  const lockoutBox = document.getElementById('lockoutBox');
  const attemptsRow = document.getElementById('attemptsRow');
  const submitBtn = document.getElementById('loginSubmitBtn');

  if (loginState.lockedUntil && Date.now() < loginState.lockedUntil) return;

  if (success) {
    showToast('Signed in successfully', 'success');
    return;
  }

  loginState.attempts++;
  if (attemptsRow) {
    [...attemptsRow.children].forEach((dot, i) => {
      dot.classList.toggle('used', i < loginState.attempts);
    });
  }

  if (loginState.attempts >= loginState.maxAttempts) {
    loginState.lockedUntil = Date.now() + 15 * 60 * 1000; // 15 min, mirrors backend policy
    if (lockoutBox) {
      lockoutBox.classList.add('show');
      lockoutBox.innerHTML = `🔒 Too many failed attempts. Account locked for <span class="lockout-timer" id="lockoutTimer">15:00</span> as a brute-force protection.`;
    }
    if (submitBtn) submitBtn.disabled = true;
    tickLockoutTimer();
  } else {
    showToast(`Incorrect password — ${loginState.maxAttempts - loginState.attempts} attempt(s) left`, 'error');
  }
}

function tickLockoutTimer() {
  const el = document.getElementById('lockoutTimer');
  if (!el || !loginState.lockedUntil) return;
  const remainingMs = loginState.lockedUntil - Date.now();
  if (remainingMs <= 0) {
    document.getElementById('lockoutBox')?.classList.remove('show');
    document.getElementById('loginSubmitBtn').disabled = false;
    loginState.attempts = 0;
    loginState.lockedUntil = null;
    return;
  }
  const mins = Math.floor(remainingMs / 60000);
  const secs = Math.floor((remainingMs % 60000) / 1000);
  el.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
  setTimeout(tickLockoutTimer, 1000);
}

// ---------- Diary / Vault unlock session timer ----------
function startUnlockSessionTimer(displayId, minutes = 15, onExpire) {
  let remaining = minutes * 60;
  const el = document.getElementById(displayId);
  const tick = () => {
    if (!el) return;
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    el.textContent = `Session unlocked · ${m}:${s.toString().padStart(2, '0')}`;
    if (remaining <= 0) { onExpire && onExpire(); return; }
    remaining--;
    setTimeout(tick, 1000);
  };
  tick();
}

// ---------- Circular progress (budget) ----------
function drawCircularProgress(svgId, percent, colorVar = '--teal-light') {
  const circle = document.querySelector(`#${svgId} .cp-fill`);
  if (!circle) return;
  const radius = circle.r.baseVal.value;
  const circumference = 2 * Math.PI * radius;
  circle.style.strokeDasharray = `${circumference} ${circumference}`;
  const offset = circumference - (Math.min(percent, 100) / 100) * circumference;
  circle.style.strokeDashoffset = offset;
  circle.style.stroke = getComputedStyle(document.documentElement).getPropertyValue(colorVar) || '#3FA796';
}

// ---------- Dropzone (vault upload) ----------
function initDropzone(zoneId, inputId, onFiles) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;
  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => onFiles(input.files));
  ['dragenter', 'dragover'].forEach(evt =>
    zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.add('drag-over'); })
  );
  ['dragleave', 'drop'].forEach(evt =>
    zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.remove('drag-over'); })
  );
  zone.addEventListener('drop', (e) => onFiles(e.dataTransfer.files));
}

// ---------- Mobile sidebar (hamburger, if present) ----------
function initMobileNav() {
  const btn = document.getElementById('mobileNavToggle');
  const sidebar = document.querySelector('.sidebar');
  if (!btn || !sidebar) return;
  btn.addEventListener('click', () => sidebar.classList.toggle('mobile-open'));
}
document.addEventListener('DOMContentLoaded', initMobileNav);
