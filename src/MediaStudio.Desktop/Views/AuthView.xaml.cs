using System.ComponentModel;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Views;

public partial class AuthView : UserControl
{
    private AccountViewModel? _vm;

    public AuthView()
    {
        InitializeComponent();
        DataContextChanged += (_, _) =>
        {
            if (_vm is not null) _vm.PasswordsCleared -= OnPasswordsCleared;
            _vm = DataContext as AccountViewModel;
            if (_vm is not null) _vm.PasswordsCleared += OnPasswordsCleared;
        };
        IsVisibleChanged += (_, _) => { if (IsVisible) Dispatcher.BeginInvoke(() => EmailBox.Focus()); };
    }

    // PasswordBox cannot be data-bound; copy the value into the view model.
    private void OnPasswordChanged(object sender, RoutedEventArgs e) { if (_vm is not null) _vm.Password = PasswordInput.Password; }
    private void OnConfirmChanged(object sender, RoutedEventArgs e) { if (_vm is not null) _vm.ConfirmPassword = ConfirmInput.Password; }

    private void OnPasswordsCleared(object? sender, EventArgs e)
    {
        PasswordInput.Clear();
        ConfirmInput.Clear();
    }
}

/// <summary>Visible when any bound boolean is true.</summary>
public sealed class AnyTrueVisibilityConverter : IMultiValueConverter
{
    public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture) =>
        values.Any(v => v is true) ? Visibility.Visible : Visibility.Collapsed;

    public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
