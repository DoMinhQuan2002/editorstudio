using System.Diagnostics;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MediaStudio.Desktop.Services;

/// <summary>Google sign-in for a desktop app: opens the system browser, receives the code on a
/// loopback address (http://127.0.0.1:PORT/) and exchanges it with PKCE for an id_token.
/// Needs an OAuth client of type "Desktop app" in Google Cloud Console.</summary>
public static class GoogleDesktopSignIn
{
    public static async Task<string> GetIdTokenAsync(string clientId, string clientSecret, CancellationToken cancel)
    {
        if (string.IsNullOrWhiteSpace(clientId))
            throw new AccountApiException(0, "google_not_configured", "Đăng nhập Google chưa được cấu hình.");

        var port = FreePort();
        var redirect = $"http://127.0.0.1:{port}/";
        var verifier = Base64Url(RandomNumberGenerator.GetBytes(32));
        var challenge = Base64Url(SHA256.HashData(Encoding.ASCII.GetBytes(verifier)));
        var state = Base64Url(RandomNumberGenerator.GetBytes(16));

        using var listener = new HttpListener();
        listener.Prefixes.Add(redirect);
        listener.Start();

        var url = "https://accounts.google.com/o/oauth2/v2/auth" +
                  $"?client_id={Uri.EscapeDataString(clientId)}&redirect_uri={Uri.EscapeDataString(redirect)}" +
                  "&response_type=code&scope=openid%20email%20profile&prompt=select_account" +
                  $"&code_challenge={challenge}&code_challenge_method=S256&state={state}";
        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });

        var contextTask = listener.GetContextAsync();
        var finished = await Task.WhenAny(contextTask, Task.Delay(TimeSpan.FromMinutes(3), cancel));
        if (finished != contextTask)
            throw new AccountApiException(0, "google_cancelled", "Đã hủy đăng nhập Google.");
        var context = await contextTask;
        var query = context.Request.QueryString;
        await RespondAsync(context.Response, query["code"] is not null);

        if (query["state"] != state || query["code"] is null)
            throw new AccountApiException(0, "google_cancelled", "Đăng nhập Google không hoàn tất.");

        using var http = new HttpClient();
        var response = await http.PostAsync("https://oauth2.googleapis.com/token", new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["code"] = query["code"]!, ["client_id"] = clientId, ["client_secret"] = clientSecret,
            ["redirect_uri"] = redirect, ["grant_type"] = "authorization_code", ["code_verifier"] = verifier,
        }), cancel);
        using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancel));
        if (!response.IsSuccessStatusCode || !json.RootElement.TryGetProperty("id_token", out var idToken))
            throw new AccountApiException(0, "google_failed", "Google không trả về thông tin đăng nhập.");
        return idToken.GetString()!;
    }

    private static async Task RespondAsync(HttpListenerResponse response, bool ok)
    {
        var text = ok ? "Đăng nhập thành công. Bạn có thể đóng tab này và quay lại Media Studio."
                      : "Đăng nhập chưa hoàn tất. Hãy quay lại Media Studio.";
        var html = $"<!doctype html><meta charset=utf-8><body style=\"font-family:Segoe UI;background:#F6F8FD;display:flex;" +
                   $"align-items:center;justify-content:center;height:100vh\"><h2 style=\"color:#161A2B\">{text}</h2></body>";
        var bytes = Encoding.UTF8.GetBytes(html);
        response.ContentType = "text/html; charset=utf-8";
        response.ContentLength64 = bytes.Length;
        await response.OutputStream.WriteAsync(bytes);
        response.Close();
    }

    private static int FreePort()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        var port = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return port;
    }

    private static string Base64Url(byte[] data) => Convert.ToBase64String(data).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
