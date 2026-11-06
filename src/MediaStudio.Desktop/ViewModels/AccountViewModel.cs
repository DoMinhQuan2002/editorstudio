using System.Collections.ObjectModel;
using System.Globalization;
using System.Windows;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

public enum AuthMode { Login, Signup, VerifyOtp, Forgot, Reset }

/// <summary>Sign-in / sign-up screen, account menu and plan picker.</summary>
public sealed class AccountViewModel : ObservableObject
{
    private readonly AccountService _account;
    private AuthMode _mode = AuthMode.Login;
    private string _email = "", _displayName = "", _otpCode = "", _error = "", _info = "", _remoteNotice = "";
    private bool _isBusy, _isStarting = true, _isPlanPickerOpen;
    private string _planPickerMessage = "";
    private CancellationTokenSource? _googleCancel;

    public AccountViewModel(AccountService account)
    {
        _account = account;
        _account.SessionChanged += (_, _) => OnUi(RaiseSessionProperties);
        _account.SignedOutRemotely += (_, message) => OnUi(() =>
        {
            RemoteNotice = message;
            Mode = AuthMode.Login;
            IsPlanPickerOpen = false;
        });

        ShowLoginCommand = new RelayCommand(_ => Switch(AuthMode.Login));
        ShowSignupCommand = new RelayCommand(_ => Switch(AuthMode.Signup));
        ShowForgotCommand = new RelayCommand(_ => Switch(AuthMode.Forgot));
        LoginCommand = new AsyncRelayCommand(() => Run(async () => await _account.LoginAsync(Email.Trim(), Password)));
        SignupCommand = new AsyncRelayCommand(() => Run(async () =>
        {
            if (Password != ConfirmPassword) throw new AccountApiException(0, "mismatch", "Hai mật khẩu không khớp.");
            await _account.SignupStartAsync(Email.Trim(), Password, string.IsNullOrWhiteSpace(DisplayName) ? null : DisplayName.Trim());
            OtpCode = "";
            Mode = AuthMode.VerifyOtp;
            Info = $"Đã gửi mã 6 số đến {Email.Trim()}. Mã có hiệu lực trong 5 phút.";
        }));
        VerifyOtpCommand = new AsyncRelayCommand(() => Run(async () => await _account.SignupVerifyAsync(Email.Trim(), OtpCode.Trim())));
        ResendOtpCommand = new AsyncRelayCommand(() => Run(async () =>
        {
            await _account.ResendOtpAsync(Email.Trim(), Mode == AuthMode.Reset ? "reset_password" : "signup");
            Info = "Đã gửi lại mã. Kiểm tra cả thư mục Spam.";
        }));
        ForgotCommand = new AsyncRelayCommand(() => Run(async () =>
        {
            await _account.ForgotPasswordAsync(Email.Trim());
            OtpCode = "";
            Mode = AuthMode.Reset;
            Info = "Nếu email có tài khoản, mã đặt lại mật khẩu đã được gửi.";
        }));
        ResetCommand = new AsyncRelayCommand(() => Run(async () =>
        {
            if (Password != ConfirmPassword) throw new AccountApiException(0, "mismatch", "Hai mật khẩu không khớp.");
            await _account.ResetPasswordAsync(Email.Trim(), OtpCode.Trim(), Password);
            Mode = AuthMode.Login;
            Info = "Đã đổi mật khẩu. Hãy đăng nhập bằng mật khẩu mới.";
        }));
        GoogleCommand = new AsyncRelayCommand(() => Run(async () =>
        {
            _googleCancel = new CancellationTokenSource();
            Info = "Đang mở trình duyệt để đăng nhập Google…";
            var idToken = await GoogleDesktopSignIn.GetIdTokenAsync(_account.Settings.GoogleClientId,
                _account.Settings.GoogleClientSecret, _googleCancel.Token);
            await _account.LoginWithGoogleAsync(idToken);
        }));
        FacebookCommand = new RelayCommand(_ =>
            Error = "Đăng nhập Facebook sẽ có khi ứng dụng Facebook Login được tạo. Hiện bạn có thể dùng email hoặc Google.");
        LogoutCommand = new AsyncRelayCommand(async () => { await _account.LogoutAsync(); Switch(AuthMode.Login); });
        DismissNoticeCommand = new RelayCommand(_ => RemoteNotice = "");
        ClosePlanPickerCommand = new RelayCommand(_ => IsPlanPickerOpen = false);
    }

    // ------------------------------------------------------------------ state
    public bool IsSignedIn => _account.IsSignedIn;
    public bool IsAuthVisible => !IsStarting && !_account.IsSignedIn;
    public bool IsStarting { get => _isStarting; private set { if (SetProperty(ref _isStarting, value)) OnPropertyChanged(nameof(IsAuthVisible)); } }
    public AuthMode Mode
    {
        get => _mode;
        private set
        {
            if (!SetProperty(ref _mode, value)) return;
            OnPropertyChanged(nameof(IsLoginMode)); OnPropertyChanged(nameof(IsSignupMode)); OnPropertyChanged(nameof(IsOtpMode));
            OnPropertyChanged(nameof(IsForgotMode)); OnPropertyChanged(nameof(IsResetMode)); OnPropertyChanged(nameof(Heading));
            OnPropertyChanged(nameof(SubHeading));
            PasswordsCleared?.Invoke(this, EventArgs.Empty);
        }
    }
    public bool IsLoginMode => Mode == AuthMode.Login;
    public bool IsSignupMode => Mode == AuthMode.Signup;
    public bool IsOtpMode => Mode == AuthMode.VerifyOtp;
    public bool IsForgotMode => Mode == AuthMode.Forgot;
    public bool IsResetMode => Mode == AuthMode.Reset;
    public string Heading => Mode switch
    {
        AuthMode.Signup => "Tạo tài khoản",
        AuthMode.VerifyOtp => "Xác nhận email",
        AuthMode.Forgot => "Quên mật khẩu",
        AuthMode.Reset => "Đặt mật khẩu mới",
        _ => "Đăng nhập",
    };
    public string SubHeading => Mode switch
    {
        AuthMode.Signup => "Đăng ký bằng Gmail, chúng tôi sẽ gửi mã xác nhận đến email của bạn.",
        AuthMode.VerifyOtp => "Nhập mã 6 số vừa được gửi đến email của bạn.",
        AuthMode.Forgot => "Nhập email đã đăng ký để nhận mã đặt lại mật khẩu.",
        AuthMode.Reset => "Nhập mã trong email và mật khẩu mới.",
        _ => "Chào mừng trở lại Media Studio.",
    };

    public string Email { get => _email; set => SetProperty(ref _email, value); }
    public string DisplayName { get => _displayName; set => SetProperty(ref _displayName, value); }
    // Keep digits only: codes copied from Gmail often carry spaces or line breaks.
    public string OtpCode
    {
        get => _otpCode;
        set => SetProperty(ref _otpCode, new string((value ?? "").Where(char.IsAsciiDigit).Take(6).ToArray()));
    }
    public string Password { get; set; } = "";          // set from PasswordBox in code-behind
    public string ConfirmPassword { get; set; } = "";
    public string Error { get => _error; private set { if (SetProperty(ref _error, value)) OnPropertyChanged(nameof(HasError)); } }
    public bool HasError => !string.IsNullOrEmpty(Error);
    public string Info { get => _info; private set { if (SetProperty(ref _info, value)) OnPropertyChanged(nameof(HasInfo)); } }
    public bool HasInfo => !string.IsNullOrEmpty(Info);
    public bool IsBusy { get => _isBusy; private set => SetProperty(ref _isBusy, value); }
    public string RemoteNotice { get => _remoteNotice; private set { if (SetProperty(ref _remoteNotice, value)) OnPropertyChanged(nameof(HasRemoteNotice)); } }
    public bool HasRemoteNotice => !string.IsNullOrEmpty(RemoteNotice);

    public string UserEmail => _account.User?.Email ?? "";
    public string UserName => _account.User?.DisplayName ?? _account.User?.Email ?? "";
    public string UserInitial => string.IsNullOrEmpty(UserName) ? "?" : UserName[..1].ToUpperInvariant();
    public string PlanLabel => _account.Entitlements is { } e
        ? e.PlanCode == "free" ? "Gói Miễn phí"
          : $"Gói {e.PlanName}" + (e.ActiveUntil is { } until ? $" · đến {until.ToLocalTime():dd/MM/yyyy}" : "")
        : "";

    public event EventHandler? PasswordsCleared;

    // ------------------------------------------------------------------ plan picker
    public bool IsPlanPickerOpen { get => _isPlanPickerOpen; private set => SetProperty(ref _isPlanPickerOpen, value); }
    public string PlanPickerMessage { get => _planPickerMessage; private set => SetProperty(ref _planPickerMessage, value); }
    public ObservableCollection<PlanOption> PlanOptions { get; } = [];

    public async Task OpenPlanPickerAsync(string message)
    {
        PlanPickerMessage = message;
        IsPlanPickerOpen = true;
        try
        {
            var plans = await _account.GetPlansAsync();
            PlanOptions.Clear();
            foreach (var plan in plans.Where(p => p.Code != "free"))
                foreach (var price in plan.Prices)
                    PlanOptions.Add(new PlanOption(plan.Name, price));
        }
        catch (Exception error) { PlanPickerMessage = message + "\n" + error.Message; }
    }

    /// <summary>Called before an export. True = go ahead.</summary>
    public async Task<bool> CheckExportAsync(string templateSlug)
    {
        var (result, message) = await _account.CheckExportAsync(templateSlug);
        switch (result)
        {
            case ExportGateResult.Allowed:
                return true;
            case ExportGateResult.PlanRequired:
                await OpenPlanPickerAsync(message);
                return false;
            case ExportGateResult.SignedOut:
                return false;   // the sign-in screen is already showing
            default:
                MessageBox.Show($"Không kiểm tra được gói của bạn.\n\n{message}", "Media Studio",
                    MessageBoxButton.OK, MessageBoxImage.Warning);
                return false;
        }
    }

    // ------------------------------------------------------------------ commands
    public RelayCommand ShowLoginCommand { get; }
    public RelayCommand ShowSignupCommand { get; }
    public RelayCommand ShowForgotCommand { get; }
    public AsyncRelayCommand LoginCommand { get; }
    public AsyncRelayCommand SignupCommand { get; }
    public AsyncRelayCommand VerifyOtpCommand { get; }
    public AsyncRelayCommand ResendOtpCommand { get; }
    public AsyncRelayCommand ForgotCommand { get; }
    public AsyncRelayCommand ResetCommand { get; }
    public AsyncRelayCommand GoogleCommand { get; }
    public RelayCommand FacebookCommand { get; }
    public AsyncRelayCommand LogoutCommand { get; }
    public RelayCommand DismissNoticeCommand { get; }
    public RelayCommand ClosePlanPickerCommand { get; }

    /// <summary>Startup: silent sign-in with the saved session.</summary>
    public async Task StartAsync()
    {
        try { await _account.TryRestoreAsync(); }
        catch (AccountApiException error) when (error.Code == "signed_in_elsewhere") { RemoteNotice = error.Message; }
        catch (AccountApiException error) { Error = error.Message; }
        finally { IsStarting = false; RaiseSessionProperties(); }
    }

    private void Switch(AuthMode mode)
    {
        Error = ""; Info = "";
        Mode = mode;
    }

    private async Task Run(Func<Task> action)
    {
        if (IsBusy) return;
        IsBusy = true; Error = "";
        try { await action(); }
        catch (AccountApiException error) { Error = error.Message; }
        catch (Exception error) { Error = "Có lỗi xảy ra: " + error.Message; }
        finally { IsBusy = false; }
    }

    private void RaiseSessionProperties()
    {
        OnPropertyChanged(nameof(IsSignedIn)); OnPropertyChanged(nameof(IsAuthVisible));
        OnPropertyChanged(nameof(UserEmail)); OnPropertyChanged(nameof(UserName)); OnPropertyChanged(nameof(UserInitial));
        OnPropertyChanged(nameof(PlanLabel));
        if (_account.IsSignedIn) { Error = ""; Info = ""; OtpCode = ""; PasswordsCleared?.Invoke(this, EventArgs.Empty); }
    }

    private static void OnUi(Action action)
    {
        var dispatcher = Application.Current?.Dispatcher;
        if (dispatcher is null || dispatcher.CheckAccess()) action(); else dispatcher.BeginInvoke(action);
    }
}

public sealed class PlanOption(string planName, PlanPrice price)
{
    private static readonly CultureInfo Vi = CultureInfo.GetCultureInfo("vi-VN");
    public string Title => $"{planName} · " + price.BillingPeriod switch { "week" => "Tuần", "month" => "Tháng", _ => "Năm" };
    public string PriceText => price.Amount.ToString("#,0", Vi) + "đ";
    public string PeriodText => price.BillingPeriod switch { "week" => "/ tuần", "month" => "/ tháng", _ => "/ năm" };
    public bool IsPopular => price.BillingPeriod == "year";
}
