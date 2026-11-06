using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace MediaStudio.Desktop.Services;

/// <summary>Settings for the account server, read from account-settings.json next to the exe.
/// MEDIASTUDIO_ACCOUNT_API overrides the server address.</summary>
public sealed class AccountSettings
{
    public string ApiBaseUrl { get; set; } = "http://localhost:8800";
    public string GoogleClientId { get; set; } = "";
    public string GoogleClientSecret { get; set; } = "";
    public string FacebookAppId { get; set; } = "";

    public static AccountSettings Load()
    {
        var settings = new AccountSettings();
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "account-settings.json");
            if (File.Exists(path))
                settings = JsonSerializer.Deserialize<AccountSettings>(File.ReadAllText(path),
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true, ReadCommentHandling = JsonCommentHandling.Skip })
                    ?? settings;
        }
        catch { /* fall back to defaults */ }
        var env = Environment.GetEnvironmentVariable("MEDIASTUDIO_ACCOUNT_API");
        if (!string.IsNullOrWhiteSpace(env)) settings.ApiBaseUrl = env;
        settings.ApiBaseUrl = settings.ApiBaseUrl.TrimEnd('/');
        return settings;
    }
}

public sealed class AccountApiException(int status, string code, string message) : Exception(message)
{
    public int Status { get; } = status;
    public string Code { get; } = code;
}

public sealed record AccountUser(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("email")] string Email,
    [property: JsonPropertyName("display_name")] string? DisplayName,
    [property: JsonPropertyName("avatar_url")] string? AvatarUrl,
    [property: JsonPropertyName("email_verified")] bool EmailVerified,
    [property: JsonPropertyName("providers")] List<string> Providers);

public sealed record AccountEntitlements(
    [property: JsonPropertyName("plan_code")] string PlanCode,
    [property: JsonPropertyName("plan_name")] string PlanName,
    [property: JsonPropertyName("billing_period")] string? BillingPeriod,
    [property: JsonPropertyName("active_until")] DateTimeOffset? ActiveUntil,
    [property: JsonPropertyName("features")] List<string> Features);

public sealed record AccountSession(
    [property: JsonPropertyName("access_token")] string AccessToken,
    [property: JsonPropertyName("expires_in")] int ExpiresIn,
    [property: JsonPropertyName("refresh_token")] string RefreshToken,
    [property: JsonPropertyName("user")] AccountUser User,
    [property: JsonPropertyName("entitlements")] AccountEntitlements Entitlements);

public sealed record AccountMe(
    [property: JsonPropertyName("user")] AccountUser User,
    [property: JsonPropertyName("entitlements")] AccountEntitlements Entitlements);

public sealed record PlanPrice(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("billing_period")] string BillingPeriod,
    [property: JsonPropertyName("amount")] decimal Amount,
    [property: JsonPropertyName("currency")] string Currency);

public sealed record PlanInfo(
    [property: JsonPropertyName("code")] string Code,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("description")] string? Description,
    [property: JsonPropertyName("features")] List<string> Features,
    [property: JsonPropertyName("prices")] List<PlanPrice> Prices);

public enum ExportGateResult { Allowed, PlanRequired, SignedOut, Error }

/// <summary>Talks to the Media Studio account server: sign-up with e-mail OTP, sign-in
/// (password / Google / Facebook), token refresh, plan checks. Keeps the refresh token
/// encrypted for the current Windows user (DPAPI).</summary>
public sealed class AccountService
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private readonly HttpClient _http;
    private readonly string _dataDir;
    private AccountSession? _session;
    private DateTimeOffset _accessExpires;

    public AccountService(AccountSettings settings)
    {
        Settings = settings;
        _http = new HttpClient { BaseAddress = new Uri(settings.ApiBaseUrl + "/"), Timeout = TimeSpan.FromSeconds(45) };
        _dataDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MediaStudio");
        Directory.CreateDirectory(_dataDir);
        DeviceKey = LoadOrCreateDeviceKey();
    }

    public AccountSettings Settings { get; }
    public string DeviceKey { get; }
    public AccountUser? User => _session?.User;
    public AccountEntitlements? Entitlements { get; private set; }
    public bool IsSignedIn => _session is not null;

    /// <summary>Raised (on a worker thread) when another machine signs in with this account.</summary>
    public event EventHandler<string>? SignedOutRemotely;
    public event EventHandler? SessionChanged;

    // ------------------------------------------------------------------ sign-up / sign-in
    public Task SignupStartAsync(string email, string password, string? name) =>
        PostAsync<JsonElement>("auth/signup/start", new { email, password, display_name = name });

    public async Task SignupVerifyAsync(string email, string code) =>
        SetSession(await PostAsync<AccountSession>("auth/signup/verify", new { email, code, device = DevicePayload() }));

    public Task ResendOtpAsync(string email, string purpose) =>
        PostAsync<JsonElement>("auth/otp/resend", new { email, purpose });

    public async Task LoginAsync(string email, string password) =>
        SetSession(await PostAsync<AccountSession>("auth/login", new { email, password, device = DevicePayload() }));

    public async Task LoginWithGoogleAsync(string idToken) =>
        SetSession(await PostAsync<AccountSession>("auth/google", new { id_token = idToken, device = DevicePayload() }));

    public async Task LoginWithFacebookAsync(string accessToken) =>
        SetSession(await PostAsync<AccountSession>("auth/facebook", new { access_token = accessToken, device = DevicePayload() }));

    public Task ForgotPasswordAsync(string email) => PostAsync<JsonElement>("auth/password/forgot", new { email });

    public Task ResetPasswordAsync(string email, string code, string newPassword) =>
        PostAsync<JsonElement>("auth/password/reset", new { email, code, new_password = newPassword });

    /// <summary>Signs in silently with the saved refresh token. False when there is none or it no longer works.</summary>
    public async Task<bool> TryRestoreAsync()
    {
        var saved = LoadRefreshToken();
        if (saved is null) return false;
        try
        {
            SetSession(await PostAsync<AccountSession>("auth/refresh", new { refresh_token = saved, device_key = DeviceKey }));
            return true;
        }
        catch (AccountApiException error) when (error.Status == 401)
        {
            ClearSession();
            if (error.Code == "signed_in_elsewhere") throw;
            return false;
        }
    }

    public async Task LogoutAsync()
    {
        try { await SendAuthorizedAsync(HttpMethod.Post, "auth/logout", null); } catch { /* sign out locally anyway */ }
        ClearSession();
    }

    // ------------------------------------------------------------------ plans & export gate
    public Task<List<PlanInfo>> GetPlansAsync() => GetAsync<List<PlanInfo>>("billing/plans");

    public async Task<AccountMe> RefreshMeAsync()
    {
        var me = await ReadAsync<AccountMe>(await SendAuthorizedAsync(HttpMethod.Get, "me", null));
        Entitlements = me.Entitlements;
        SessionChanged?.Invoke(this, EventArgs.Empty);
        return me;
    }

    public async Task<(ExportGateResult Result, string Message)> CheckExportAsync(string templateSlug)
    {
        try
        {
            await ReadAsync<JsonElement>(await SendAuthorizedAsync(HttpMethod.Post, "exports/check", new { template_slug = templateSlug }));
            return (ExportGateResult.Allowed, "");
        }
        catch (AccountApiException error) when (error.Status == 402) { return (ExportGateResult.PlanRequired, error.Message); }
        catch (AccountApiException error) when (error.Status == 401) { return (ExportGateResult.SignedOut, error.Message); }
        catch (Exception error) { return (ExportGateResult.Error, error.Message); }
    }

    // ------------------------------------------------------------------ plumbing
    private object DevicePayload() => new
    {
        device_key = DeviceKey,
        device_name = Environment.MachineName,
        os = Environment.OSVersion.VersionString,
        app_version = typeof(AccountService).Assembly.GetName().Version?.ToString(3) ?? "0.1.0",
    };

    private void SetSession(AccountSession session)
    {
        _session = session;
        Entitlements = session.Entitlements;
        _accessExpires = DateTimeOffset.UtcNow.AddSeconds(Math.Max(30, session.ExpiresIn - 30));
        SaveRefreshToken(session.RefreshToken);
        SessionChanged?.Invoke(this, EventArgs.Empty);
    }

    private void ClearSession()
    {
        _session = null;
        Entitlements = null;
        SaveRefreshToken(null);
        SessionChanged?.Invoke(this, EventArgs.Empty);
    }

    private async Task<HttpResponseMessage> SendAuthorizedAsync(HttpMethod method, string path, object? body)
    {
        if (_session is null) throw new AccountApiException(401, "not_authenticated", "Bạn cần đăng nhập.");
        if (DateTimeOffset.UtcNow >= _accessExpires) await RefreshAsync();
        var response = await SendOnceAsync(method, path, body);
        if (response.StatusCode == HttpStatusCode.Unauthorized && await ErrorCodeAsync(response) == "token_expired")
        {
            await RefreshAsync();
            response = await SendOnceAsync(method, path, body);
        }
        return response;
    }

    private async Task<HttpResponseMessage> SendOnceAsync(HttpMethod method, string path, object? body)
    {
        var request = new HttpRequestMessage(method, path);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _session?.AccessToken);
        if (body is not null) request.Content = JsonContent.Create(body, options: Json);
        return await SendAsync(request);
    }

    private async Task RefreshAsync()
    {
        if (_session is null) return;
        try
        {
            SetSession(await PostAsync<AccountSession>("auth/refresh", new { refresh_token = _session.RefreshToken, device_key = DeviceKey }));
        }
        catch (AccountApiException error) when (error.Status == 401)
        {
            ClearSession();
            throw;
        }
    }

    private async Task<T> GetAsync<T>(string path) => await ReadAsync<T>(await SendAsync(new HttpRequestMessage(HttpMethod.Get, path)));

    private async Task<T> PostAsync<T>(string path, object body) =>
        await ReadAsync<T>(await SendAsync(new HttpRequestMessage(HttpMethod.Post, path) { Content = JsonContent.Create(body, options: Json) }));

    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request)
    {
        try { return await _http.SendAsync(request); }
        catch (TaskCanceledException)
        {
            throw new AccountApiException(0, "timeout",
                $"Máy chủ tài khoản ({Settings.ApiBaseUrl}) không phản hồi kịp. Nếu đang gửi mã, có thể Gmail gửi chậm; hãy thử lại sau ít phút.");
        }
        catch (HttpRequestException)
        {
            throw new AccountApiException(0, "offline",
                $"Không kết nối được máy chủ tài khoản ({Settings.ApiBaseUrl}). Hãy kiểm tra server đang chạy rồi thử lại.");
        }
    }

    private async Task<T> ReadAsync<T>(HttpResponseMessage response)
    {
        if (response.IsSuccessStatusCode)
            return (await response.Content.ReadFromJsonAsync<T>(Json))!;
        var (code, message) = await ErrorAsync(response);
        if (code == "signed_in_elsewhere")
        {
            ClearSession();
            SignedOutRemotely?.Invoke(this, message);
        }
        throw new AccountApiException((int)response.StatusCode, code, message);
    }

    private static async Task<string> ErrorCodeAsync(HttpResponseMessage response) => (await ErrorAsync(response)).Code;

    private static async Task<(string Code, string Message)> ErrorAsync(HttpResponseMessage response)
    {
        try
        {
            await response.Content.LoadIntoBufferAsync();
            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var detail = doc.RootElement.GetProperty("detail");
            if (detail.ValueKind == JsonValueKind.Object)
                return (detail.GetProperty("code").GetString() ?? "error", detail.GetProperty("message").GetString() ?? "Có lỗi xảy ra.");
            if (detail.ValueKind == JsonValueKind.Array)   // FastAPI validation errors
                return ("invalid_input", "Thông tin nhập chưa hợp lệ. Kiểm tra email, mật khẩu (tối thiểu 8 ký tự) và mã 6 số.");
        }
        catch { /* not JSON */ }
        return ("http_" + (int)response.StatusCode, $"Máy chủ trả lỗi {(int)response.StatusCode}.");
    }

    private string LoadOrCreateDeviceKey()
    {
        var path = Path.Combine(_dataDir, "device.id");
        try
        {
            if (File.Exists(path)) { var key = File.ReadAllText(path).Trim(); if (key.Length >= 8) return key; }
            var created = Guid.NewGuid().ToString("N");
            File.WriteAllText(path, created);
            return created;
        }
        catch { return Environment.MachineName + "-" + Environment.UserName; }
    }

    private string TokenPath => Path.Combine(_dataDir, "session.bin");

    private void SaveRefreshToken(string? token)
    {
        try
        {
            if (token is null) { if (File.Exists(TokenPath)) File.Delete(TokenPath); return; }
            File.WriteAllBytes(TokenPath, ProtectedData.Protect(Encoding.UTF8.GetBytes(token), null, DataProtectionScope.CurrentUser));
        }
        catch { /* not fatal: the user just signs in again next time */ }
    }

    private string? LoadRefreshToken()
    {
        try
        {
            return File.Exists(TokenPath)
                ? Encoding.UTF8.GetString(ProtectedData.Unprotect(File.ReadAllBytes(TokenPath), null, DataProtectionScope.CurrentUser))
                : null;
        }
        catch { return null; }
    }
}
