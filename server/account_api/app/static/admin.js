(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const state = { admin: null, page: "overview", categories: [], templates: [], audioTracks: [], versions: [], assets: [], timers: {} };
  const pageTitles = {
    overview: "Tổng quan",
    users: "Tài khoản",
    billing: "Gói & thanh toán",
    templates: "Mẫu video & story",
    assets: "Nhạc & tài nguyên",
    activity: "Nhật ký quản trị",
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(`/admin/api${path}`, { ...options, headers, credentials: "same-origin" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail;
      const message = typeof detail === "string" ? detail : detail?.message || `Yêu cầu thất bại (${response.status})`;
      const error = new Error(message);
      error.status = response.status;
      error.code = detail?.code;
      throw error;
    }
    return payload;
  }

  function showLogin(message = "") {
    $("#admin-shell").hidden = true;
    $("#password-dialog").hidden = true;
    $("#login-screen").hidden = false;
    const error = $("#login-error");
    error.textContent = message;
    error.hidden = !message;
    $("#login-form").reset();
  }

  function showShell(admin) {
    state.admin = admin;
    $("#login-screen").hidden = true;
    $("#admin-shell").hidden = false;
    const name = admin.display_name || admin.email;
    $("#admin-name").textContent = name;
    $("#admin-role").textContent = admin.role === "super_admin" ? "Quản trị viên cấp cao" : admin.role;
    const initials = name.trim().split(/\s+/).slice(-2).map((part) => part[0]).join("").toUpperCase() || "AD";
    $("#admin-avatar").textContent = initials;
    $("#top-avatar").textContent = initials;
  }

  function openPasswordDialog(required = false) {
    $("#password-title").textContent = required ? "Đặt mật khẩu mới" : "Đổi mật khẩu";
    $("#password-intro").textContent = required
      ? "Đây là lần đăng nhập đầu tiên. Hãy đổi mật khẩu tạm trước khi vào trang quản trị."
      : "Nhập mật khẩu hiện tại và mật khẩu mới. Mật khẩu mới cần có ít nhất 12 ký tự.";
    $("#close-password-dialog").hidden = required;
    $("#password-dialog").hidden = false;
  }

  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.add("visible");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => node.classList.remove("visible"), 2600);
  }

  function showGlobalError(message) {
    const node = $("#global-error");
    node.textContent = message;
    node.hidden = !message;
  }

  function formatDate(value, withTime = false) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("vi-VN", withTime
      ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
      : { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
  }

  function formatVnd(value, currency = "VND") {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return new Intl.NumberFormat("vi-VN", { style: "currency", currency, maximumFractionDigits: 0 }).format(number);
  }

  function statusPill(status, verified) {
    if (status === "active") return `<span class="pill green">${verified ? "Hoạt động" : "Chưa xác minh"}</span>`;
    if (status === "locked") return '<span class="pill red">Đã khóa</span>';
    if (status === "pending") return '<span class="pill orange">Chờ xác minh</span>';
    if (status === "deleted") return '<span class="pill neutral">Đã xóa</span>';
    return `<span class="pill neutral">${escapeHtml(status || "Không rõ")}</span>`;
  }

  function paymentPill(status) {
    const className = status === "succeeded" ? "green" : status === "pending" ? "orange" : status === "failed" || status === "refunded" ? "red" : "neutral";
    const labels = { succeeded: "Thành công", pending: "Đang chờ", failed: "Thất bại", canceled: "Đã hủy", refunded: "Đã hoàn tiền" };
    return `<span class="pill ${className}">${escapeHtml(labels[status] || status)}</span>`;
  }

  function setMetrics(container, items) {
    container.innerHTML = items.map((item) => `<article class="metric"><div class="metric-label">${escapeHtml(item.label)} <span class="metric-mark">${escapeHtml(item.mark || "•")}</span></div><div class="metric-value">${escapeHtml(item.value)}</div><div class="metric-foot">${escapeHtml(item.foot || "")}</div></article>`).join("");
  }

  function emptyRow(colspan, message) {
    return `<tr><td colspan="${colspan}"><div class="empty-inline">${escapeHtml(message)}</div></td></tr>`;
  }

  async function loadPage(name = state.page) {
    state.page = name;
    showGlobalError("");
    $$(".page").forEach((page) => {
      const active = page.id === `page-${name}`;
      page.hidden = !active;
      page.classList.toggle("active", active);
    });
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === name));
    $("#breadcrumb-title").textContent = pageTitles[name] || pageTitles.overview;
    try {
      if (name === "overview") await loadOverview();
      if (name === "users") await loadUsers();
      if (name === "billing") await loadBilling();
      if (name === "templates") await loadTemplates();
      if (name === "assets") await loadAssets();
      if (name === "activity") await loadActivity();
    } catch (error) {
      if (error.status === 401) return showLogin("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.");
      showGlobalError(error.message);
    }
  }

  async function loadOverview() {
    const [data, templateData] = await Promise.all([api("/overview"), api("/templates")]);
    const m = data.metrics;
    setMetrics($("#overview-metrics"), [
      { label: "Tổng tài khoản", value: m.users_total, foot: `${m.users_active} đang hoạt động · ${m.users_unverified} chưa xác minh`, mark: "♙" },
      { label: "Gói Pro hiện hiệu lực", value: m.active_pro, foot: "Theo subscription chưa hết hạn", mark: "✧" },
      { label: "Doanh thu đã xác nhận", value: formatVnd(m.revenue_30d), foot: `30 ngày · ${m.payments_succeeded_30d} giao dịch`, mark: "₫" },
      { label: "Lượt dùng mẫu", value: "Chưa ghi nhận", foot: "Desktop chưa gửi usage events lên server", mark: "▣" },
    ]);
    renderActivityChart(data.daily_activity || []);
    const templates = templateData.templates || [];
    $("#template-summary").innerHTML = templates.length ? templates.slice(0, 5).map((template) => `
      <div class="template-row"><span class="template-tile">▣</span><span><strong>${escapeHtml(template.name)}</strong><small>${escapeHtml(template.output_kind)} · ${escapeHtml(template.slug)}</small></span><span class="template-status">${escapeHtml(template.status)}${template.is_premium ? " · Pro" : ""}</span></div>`).join("") : '<div class="empty-inline">Database chưa có template.</div>';
    $("#recent-users").innerHTML = data.recent_users.length ? data.recent_users.map((user) => `<tr><td><div class="user-cell"><span class="avatar">${escapeHtml(initials(user.display_name || user.email))}</span><span><strong>${escapeHtml(user.display_name || "Chưa đặt tên")}</strong><small>${escapeHtml(user.email)}</small></span></div></td><td>${statusPill(user.status, user.email_verified)}</td><td>${formatDate(user.created_at)}</td></tr>`).join("") : emptyRow(3, "Database chưa có tài khoản.");
    $("#recent-payments").innerHTML = data.recent_payments.length ? data.recent_payments.map((payment) => `<tr><td><strong>${escapeHtml(payment.txn_ref)}</strong><small>${escapeHtml(payment.email)}</small></td><td>${formatVnd(payment.amount, payment.currency)}</td><td>${paymentPill(payment.status)}</td></tr>`).join("") : emptyRow(3, "Chưa có giao dịch trong database.");
  }

  function initials(value) {
    return String(value || "AD").trim().split(/\s+/).slice(-2).map((part) => part[0]).join("").toUpperCase();
  }

  function renderActivityChart(days) {
    const chart = $("#activity-chart");
    const max = Math.max(0, ...days.flatMap((day) => [day.signups, day.successful_payments]));
    if (!days.length || max === 0) {
      chart.innerHTML = '<div class="empty-inline">Chưa có đăng ký hoặc thanh toán được ghi nhận trong 14 ngày gần nhất.</div>';
      return;
    }
    chart.innerHTML = days.map((day) => {
      const signupHeight = day.signups ? Math.max(4, day.signups / max * 128) : 2;
      const paymentHeight = day.successful_payments ? Math.max(4, day.successful_payments / max * 128) : 2;
      const label = new Date(`${day.date}T12:00:00`).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
      return `<div class="chart-day" title="${escapeHtml(label)} · đăng ký ${day.signups}, thanh toán ${day.successful_payments}"><div class="chart-bars"><i class="chart-bar" style="height:${signupHeight}px"></i><i class="chart-bar payments" style="height:${paymentHeight}px"></i></div><small>${escapeHtml(label)}</small></div>`;
    }).join("");
  }

  async function loadUsers() {
    const [overview, users] = await Promise.all([
      api("/overview"), fetchUsers($("#users-search").value, $("#users-status").value),
    ]);
    const m = overview.metrics;
    setMetrics($("#users-metrics"), [
      { label: "Tổng tài khoản", value: m.users_total, foot: "Đọc từ bảng users", mark: "♙" },
      { label: "Đang hoạt động", value: m.users_active, foot: "Chưa bị khóa", mark: "✓" },
      { label: "Chưa xác minh", value: m.users_unverified, foot: "Email chưa xác nhận", mark: "✉" },
      { label: "Đã khóa", value: m.users_locked, foot: "Không thể đăng nhập", mark: "⌑" },
    ]);
    $("#users-count").textContent = `${users.total} tài khoản`;
    $("#users-table").innerHTML = users.users.length ? users.users.map((user) => {
      const sub = user.subscription ? `${escapeHtml(user.subscription.name)} · đến ${formatDate(user.subscription.ends_at)}` : "Miễn phí";
      const device = user.device ? `${escapeHtml(user.device.name || user.device.os || "Thiết bị")}` : "Không có thiết bị hoạt động";
      const action = user.status === "locked" ? "Mở khóa" : "Khóa";
      const nextStatus = user.status === "locked" ? "active" : "locked";
      return `<tr><td><div class="user-cell"><span class="avatar">${escapeHtml(initials(user.display_name || user.email))}</span><span><strong>${escapeHtml(user.display_name || "Chưa đặt tên")}</strong><small>${escapeHtml(user.email)}</small></span></div></td><td>${sub}</td><td>${device}</td><td>${formatDate(user.last_login_at, true)}</td><td>${statusPill(user.status, user.email_verified)}</td><td><button class="row-action" data-user-id="${escapeHtml(user.id)}" data-next-status="${nextStatus}">${action}</button></td></tr>`;
    }).join("") : emptyRow(6, "Không tìm thấy tài khoản.");
  }

  function fetchUsers(q = "", status = "") {
    const params = new URLSearchParams({ limit: "100" });
    if (q.trim()) params.set("q", q.trim());
    if (status) params.set("status", status);
    return api(`/users?${params.toString()}`);
  }

  async function changeUserStatus(button) {
    const nextStatus = button.dataset.nextStatus;
    const reason = window.prompt(nextStatus === "locked" ? "Nhập lý do khóa tài khoản:" : "Nhập lý do mở khóa:");
    if (reason === null) return;
    if (reason.trim().length < 3) return toast("Vui lòng nhập lý do ít nhất 3 ký tự.");
    await api(`/users/${encodeURIComponent(button.dataset.userId)}/status`, {
      method: "PATCH", body: JSON.stringify({ status: nextStatus, reason: reason.trim() }),
    });
    toast("Đã cập nhật trạng thái tài khoản.");
    await loadUsers();
  }

  async function loadBilling() {
    const [overview, plans, featureData, payments] = await Promise.all([
      api("/overview"), api("/plans"), api("/features"), fetchPayments($("#payments-search").value),
    ]);
    const m = overview.metrics;
    setMetrics($("#billing-metrics"), [
      { label: "Doanh thu đã xác nhận", value: formatVnd(m.revenue_30d), foot: "30 ngày gần nhất", mark: "₫" },
      { label: "Thanh toán thành công", value: m.payments_succeeded_30d, foot: "30 ngày gần nhất", mark: "✓" },
      { label: "Đang chờ xử lý", value: m.payments_pending, foot: "Chưa có IPN kết thúc", mark: "◷" },
      { label: "Gói Pro đang hiệu lực", value: m.active_pro, foot: "Theo thời hạn subscription", mark: "✧" },
    ]);
    $("#plans-list").innerHTML = plans.plans.length ? plans.plans.map((plan) => `
      <article class="plan-card"><div class="plan-title"><span><strong>${escapeHtml(plan.name)}</strong><small class="plan-code"> · ${escapeHtml(plan.code)}</small></span><label class="check-field"><input type="checkbox" data-plan-active="${escapeHtml(plan.id)}" ${plan.is_active ? "checked" : ""}> Bán</label></div>
      ${plan.prices.length ? plan.prices.map((price) => `<div class="price-row"><label>${periodLabel(price.billing_period)}</label><input type="number" min="0" step="1000" value="${escapeHtml(price.amount)}" data-price-amount="${escapeHtml(price.id)}" aria-label="Giá ${escapeHtml(periodLabel(price.billing_period))} ${escapeHtml(plan.name)}"><span class="currency">${escapeHtml(price.currency)}</span><button type="button" data-price-save="${escapeHtml(price.id)}">Lưu giá</button></div>`).join("") : '<div class="empty-inline">Chưa có mức giá.</div>'}
      <div class="feature-options">${featureData.features.map((feature) => {
        const enabled = plan.features.some((current) => current.code === feature.code);
        return `<label class="check-field"><input type="checkbox" data-feature-code="${escapeHtml(feature.code)}" ${enabled ? "checked" : ""}>${escapeHtml(feature.name)}</label>`;
      }).join("")}</div><div class="plan-actions"><button class="row-action" data-plan-features="${escapeHtml(plan.id)}">Lưu quyền lợi</button><button class="row-action" data-plan-save="${escapeHtml(plan.id)}">Lưu trạng thái gói</button></div></article>`).join("") : '<div class="panel empty-inline">Database chưa có gói dịch vụ.</div>';
    $("#payments-table").innerHTML = payments.payments.length ? payments.payments.map((payment) => `<tr><td><strong>${escapeHtml(payment.txn_ref)}</strong><small>${escapeHtml(payment.vnp_transaction_no || "Chưa có mã VNPay")}</small></td><td>${escapeHtml(payment.user_email)}</td><td>${escapeHtml(payment.plan)} · ${escapeHtml(periodLabel(payment.billing_period))}</td><td>${formatVnd(payment.amount, payment.currency)}</td><td>${escapeHtml(payment.vnp_response_code || "—")}${payment.ipn_received_at ? `<small>IPN ${formatDate(payment.ipn_received_at, true)}</small>` : ""}</td><td>${paymentPill(payment.status)}</td><td>${formatDate(payment.created_at, true)}</td></tr>`).join("") : emptyRow(7, "Database chưa có giao dịch.");
  }

  function periodLabel(period) {
    return ({ week: "Tuần", month: "Tháng", year: "Năm" })[period] || period || "—";
  }

  function fetchPayments(q = "") {
    const params = new URLSearchParams({ limit: "100" });
    if (q.trim()) params.set("q", q.trim());
    return api(`/payments?${params.toString()}`);
  }

  async function savePrice(button) {
    const id = button.dataset.priceSave;
    const input = $(`[data-price-amount="${CSS.escape(id)}"]`);
    const amount = input.value;
    await api(`/prices/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ amount }) });
    toast("Đã lưu mức giá.");
    await loadBilling();
  }

  async function savePlan(button) {
    const id = button.dataset.planSave;
    const active = $(`[data-plan-active="${CSS.escape(id)}"]`).checked;
    await api(`/plans/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ is_active: active }) });
    toast("Đã cập nhật trạng thái gói.");
    await loadBilling();
  }

  async function savePlanFeatures(button) {
    const card = button.closest(".plan-card");
    const featureCodes = $$('[data-feature-code]:checked', card).map((input) => input.dataset.featureCode);
    await api(`/plans/${encodeURIComponent(button.dataset.planFeatures)}/features`, {
      method: "PUT", body: JSON.stringify({ feature_codes: featureCodes }),
    });
    toast("Đã cập nhật quyền lợi của gói.");
    await loadBilling();
  }

  async function loadTemplates() {
    const [templateData, categoryData] = await Promise.all([api("/templates"), api("/categories")]);
    state.templates = templateData.templates;
    state.categories = categoryData.categories;
    $("#category-chips").innerHTML = state.categories.length ? state.categories.map((category) => `<span class="category-chip">${escapeHtml(category.name)} <small>${escapeHtml(category.code)}</small></span>`).join("") : '<span class="muted">Chưa có danh mục.</span>';
    $("#template-category-select").innerHTML = '<option value="">Chưa phân loại</option>' + state.categories.map((category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`).join("");
    renderTemplates($("#templates-search").value);
  }

  function renderTemplates(query = "") {
    const needle = query.toLocaleLowerCase("vi").trim();
    const filtered = state.templates.filter((template) => !needle || `${template.name} ${template.slug}`.toLocaleLowerCase("vi").includes(needle));
    $("#templates-table").innerHTML = filtered.length ? filtered.map((template) => `<tr><td><strong>${escapeHtml(template.name)}</strong><small>${escapeHtml(template.slug)}</small><input class="template-edit-name" data-template-name="${escapeHtml(template.id)}" value="${escapeHtml(template.name)}" aria-label="Tên mẫu ${escapeHtml(template.name)}"></td><td>${escapeHtml(template.output_kind)}</td><td><select data-template-category="${escapeHtml(template.id)}"><option value="">Chưa phân loại</option>${state.categories.map((category) => `<option value="${category.id}" ${template.category_id === category.id ? "selected" : ""}>${escapeHtml(category.name)}</option>`).join("")}</select></td><td>${template.versions_count} bản</td><td><label class="check-field"><input type="checkbox" data-template-premium="${escapeHtml(template.id)}" ${template.is_premium ? "checked" : ""}> Pro</label></td><td><select data-template-status="${escapeHtml(template.id)}"><option value="draft" ${template.status === "draft" ? "selected" : ""}>Bản nháp</option><option value="published" ${template.status === "published" ? "selected" : ""}>Đã phát hành</option><option value="retired" ${template.status === "retired" ? "selected" : ""}>Ngừng phát hành</option></select></td><td><button class="row-action" data-template-save="${escapeHtml(template.id)}">Lưu</button></td></tr>`).join("") : emptyRow(7, "Không tìm thấy mẫu.");
  }

  async function saveTemplate(button) {
    const id = button.dataset.templateSave;
    const name = $(`[data-template-name="${CSS.escape(id)}"]`).value.trim();
    const category = $(`[data-template-category="${CSS.escape(id)}"]`).value;
    const premium = $(`[data-template-premium="${CSS.escape(id)}"]`).checked;
    const status = $(`[data-template-status="${CSS.escape(id)}"]`).value;
    await api(`/templates/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name, category_id: category ? Number(category) : null, is_premium: premium, status }),
    });
    toast("Đã lưu mẫu.");
    await loadTemplates();
  }

  async function createTemplate(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api("/templates", {
      method: "POST",
      body: JSON.stringify({
        slug: form.get("slug"), name: form.get("name"), output_kind: form.get("output_kind"),
        category_id: form.get("category_id") ? Number(form.get("category_id")) : null,
        is_premium: form.get("is_premium") === "on", status: "draft",
      }),
    });
    event.currentTarget.reset();
    $("#template-form-wrap").hidden = true;
    toast("Đã tạo mẫu ở trạng thái bản nháp.");
    await loadTemplates();
  }

  async function createCategory(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api("/categories", { method: "POST", body: JSON.stringify({ code: form.get("code"), name: form.get("name"), sort_order: state.categories.length }) });
    event.currentTarget.reset();
    toast("Đã thêm danh mục.");
    await loadTemplates();
  }

  async function loadAssets() {
    const [data, templateData] = await Promise.all([api("/assets"), api("/templates")]);
    state.audioTracks = data.audio_tracks;
    state.versions = data.versions;
    state.assets = data.assets;
    state.templates = templateData.templates;
    $("#audio-table").innerHTML = data.audio_tracks.length ? data.audio_tracks.map((track) => `<tr><td><strong>${escapeHtml(track.title)}</strong><small>${escapeHtml(track.artist || "")}</small></td><td>${formatDuration(track.duration_ms)}</td><td>${escapeHtml(licenseLabel(track.license))}</td></tr>`).join("") : emptyRow(3, "Chưa có audio track trong database.");
    $("#asset-version-list").innerHTML = data.versions.length ? data.versions.map((version) => `<div class="version-summary"><strong>${escapeHtml(version.template_name)} · ${escapeHtml(version.version)} ${version.is_current ? "· hiện tại" : ""}</strong><small>${version.duration_ms ? formatDuration(version.duration_ms) : ""}${version.page_count ? ` · ${version.page_count} trang` : ""}</small></div>`).join("") : '<div class="empty-inline">Chưa có phiên bản mẫu. Tạo phiên bản trước khi gắn file.</div>';
    $("#assets-table").innerHTML = data.assets.length ? data.assets.map((asset) => `<tr><td><strong>${escapeHtml(asset.kind)}</strong><small>${escapeHtml(asset.file_url)}</small></td><td>${escapeHtml(asset.template_name)} · ${escapeHtml(asset.version)}</td><td>${formatBytes(asset.byte_size)}</td></tr>`).join("") : emptyRow(3, "Chưa có file được gắn vào phiên bản mẫu.");
    $("#version-template-select").innerHTML = state.templates.map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.name)} · ${escapeHtml(template.slug)}</option>`).join("");
    $("#version-audio-select").innerHTML = '<option value="">Không gắn</option>' + data.audio_tracks.map((track) => `<option value="${escapeHtml(track.id)}">${escapeHtml(track.title)}</option>`).join("");
    $("#asset-version-select").innerHTML = data.versions.map((version) => `<option value="${escapeHtml(version.id)}">${escapeHtml(version.template_name)} · ${escapeHtml(version.version)}</option>`).join("");
    $('#asset-form button[type="submit"]').disabled = data.versions.length === 0;
  }

  function formatDuration(ms) {
    if (!ms) return "—";
    const seconds = Math.floor(Number(ms) / 1000);
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes)) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function licenseLabel(value) {
    return ({ owned: "Sở hữu", royalty_free: "Royalty-free", licensed: "Được cấp phép" })[value] || value;
  }

  async function createAudioTrack(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const bpm = form.get("bpm");
    await api("/audio-tracks", {
      method: "POST",
      body: JSON.stringify({
        title: form.get("title"), artist: form.get("artist") || null,
        duration_ms: Number(form.get("duration_ms")), bpm: bpm ? Number(bpm) : null,
        file_url: form.get("file_url"), file_sha256: form.get("file_sha256").trim(),
        license: form.get("license"), license_note: form.get("license_note") || null,
      }),
    });
    event.currentTarget.reset();
    toast("Đã lưu audio track.");
    await loadAssets();
  }

  async function createVersion(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    let definition;
    try { definition = JSON.parse(form.get("definition")); }
    catch { return toast("JSON định nghĩa template chưa hợp lệ."); }
    const duration = form.get("duration_ms");
    const pageCount = form.get("page_count");
    const audioId = form.get("default_audio_id");
    await api("/template-versions", {
      method: "POST",
      body: JSON.stringify({
        template_id: form.get("template_id"), version: form.get("version"), definition,
        min_media: Number(form.get("min_media")), max_media: Number(form.get("max_media")),
        duration_ms: duration ? Number(duration) : null,
        page_count: pageCount ? Number(pageCount) : null,
        default_audio_id: audioId || null,
        is_current: form.get("is_current") === "on",
      }),
    });
    event.currentTarget.reset();
    toast("Đã tạo phiên bản mẫu.");
    await loadAssets();
  }

  async function createAsset(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api("/template-assets", {
      method: "POST",
      body: JSON.stringify({
        template_version_id: form.get("template_version_id"), kind: form.get("kind"),
        file_url: form.get("file_url"), file_sha256: form.get("file_sha256").trim(), byte_size: Number(form.get("byte_size")),
      }),
    });
    event.currentTarget.reset();
    toast("Đã gắn file vào phiên bản mẫu.");
    await loadAssets();
  }

  async function loadActivity() {
    const data = await api("/activity?limit=100");
    const labels = {
      "admin.login": "Đăng nhập admin", "admin.logout": "Đăng xuất admin", "admin.password_changed": "Đổi mật khẩu admin",
      "user.status_changed": "Cập nhật trạng thái tài khoản", "plan.updated": "Cập nhật gói",
      "plan_price.updated": "Cập nhật giá", "template.updated": "Cập nhật mẫu", "template.created": "Tạo mẫu",
      "plan.features_updated": "Cập nhật quyền lợi gói",
      "template_category.created": "Tạo danh mục", "template_version.created": "Tạo phiên bản",
      "template_asset.created": "Gắn tài nguyên", "audio_track.created": "Thêm audio",
    };
    $("#activity-table").innerHTML = data.events.length ? data.events.map((item) => `<tr><td>${formatDate(item.created_at, true)}</td><td>${escapeHtml(item.admin_email)}</td><td>${escapeHtml(labels[item.action] || item.action)}</td><td>${escapeHtml(item.entity_type)}${item.entity_id ? `<small>${escapeHtml(item.entity_id)}</small>` : ""}</td><td>${escapeHtml(JSON.stringify(item.details || {}))}</td><td>${escapeHtml(item.ip_address || "—")}</td></tr>`).join("") : emptyRow(6, "Chưa có thao tác quản trị được ghi nhận.");
  }

  function debounce(key, callback, delay = 260) {
    clearTimeout(state.timers[key]);
    state.timers[key] = setTimeout(callback, delay);
  }

  function bindEvents() {
    $("#login-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const error = $("#login-error");
      error.hidden = true;
      try {
        const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email: form.get("email"), password: form.get("password") }) });
        showShell(data.admin);
        if (data.admin.must_change_password) openPasswordDialog(true);
        else await loadPage("overview");
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
      }
    });

    $("#password-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const error = $("#password-error");
      error.hidden = true;
      if (form.get("new_password") !== form.get("confirm_password")) {
        error.textContent = "Hai mật khẩu mới chưa khớp.";
        error.hidden = false;
        return;
      }
      try {
        const result = await api("/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: form.get("current_password"), new_password: form.get("new_password") }) });
        event.currentTarget.reset();
        $("#password-dialog").hidden = true;
        showShell(result.admin);
        toast("Đã đổi mật khẩu. Chào mừng bạn vào Media Studio Admin.");
        await loadPage("overview");
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
      }
    });

    $("#logout-button").addEventListener("click", async () => {
      try { await api("/auth/logout", { method: "POST" }); } catch { /* expire locally if the session timed out */ }
      showLogin();
    });
    $("#change-password-button").addEventListener("click", () => openPasswordDialog(false));
    $("#close-password-dialog").addEventListener("click", () => { $("#password-form").reset(); $("#password-dialog").hidden = true; });
    $$(".nav-item").forEach((button) => button.addEventListener("click", () => loadPage(button.dataset.page)));
    $$('[data-go]').forEach((button) => button.addEventListener("click", () => loadPage(button.dataset.go)));
    $$('[data-refresh]').forEach((button) => button.addEventListener("click", () => loadPage(state.page)));
    $("#users-search").addEventListener("input", () => debounce("users", () => loadUsers().catch((error) => showGlobalError(error.message))));
    $("#users-status").addEventListener("change", () => loadUsers().catch((error) => showGlobalError(error.message)));
    $("#payments-search").addEventListener("input", () => debounce("payments", () => loadBilling().catch((error) => showGlobalError(error.message))));
    $("#templates-search").addEventListener("input", (event) => renderTemplates(event.currentTarget.value));
    $("#users-table").addEventListener("click", (event) => {
      const button = event.target.closest("[data-user-id]");
      if (button) changeUserStatus(button).catch((error) => showGlobalError(error.message));
    });
    $("#plans-list").addEventListener("click", (event) => {
      const priceButton = event.target.closest("[data-price-save]");
      const planButton = event.target.closest("[data-plan-save]");
      const featureButton = event.target.closest("[data-plan-features]");
      if (priceButton) savePrice(priceButton).catch((error) => showGlobalError(error.message));
      if (planButton) savePlan(planButton).catch((error) => showGlobalError(error.message));
      if (featureButton) savePlanFeatures(featureButton).catch((error) => showGlobalError(error.message));
    });
    $("#templates-table").addEventListener("click", (event) => {
      const button = event.target.closest("[data-template-save]");
      if (button) saveTemplate(button).catch((error) => showGlobalError(error.message));
    });
    $("#show-template-form").addEventListener("click", () => { $("#template-form-wrap").hidden = false; });
    $("#hide-template-form").addEventListener("click", () => { $("#template-form-wrap").hidden = true; });
    $("#template-form").addEventListener("submit", (event) => createTemplate(event).catch((error) => showGlobalError(error.message)));
    $("#category-form").addEventListener("submit", (event) => createCategory(event).catch((error) => showGlobalError(error.message)));
    $("#audio-form").addEventListener("submit", (event) => createAudioTrack(event).catch((error) => showGlobalError(error.message)));
    $("#version-form").addEventListener("submit", (event) => createVersion(event).catch((error) => showGlobalError(error.message)));
    $("#asset-form").addEventListener("submit", (event) => createAsset(event).catch((error) => showGlobalError(error.message)));
  }

  async function init() {
    bindEvents();
    try {
      const data = await api("/auth/session");
      showShell(data.admin);
      if (data.admin.must_change_password) openPasswordDialog(true);
      else await loadPage("overview");
    } catch {
      showLogin();
    }
  }

  init();
})();
