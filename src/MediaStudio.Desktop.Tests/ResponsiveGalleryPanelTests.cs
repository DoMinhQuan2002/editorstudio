using MediaStudio.Desktop.Views;

namespace MediaStudio.Desktop.Tests;

public sealed class ResponsiveGalleryPanelTests
{
    [Theory]
    [InlineData(1366, 4)]
    [InlineData(1600, 5)]
    [InlineData(1920, 6)]
    public void GalleryColumnsRespondToWindowWidth(double windowWidth, int expectedColumns)
    {
        const double sidebarWidth = 224;
        const double galleryMargins = 56;
        var galleryWidth = windowWidth - sidebarWidth - galleryMargins;

        var columns = ResponsiveGalleryPanel.GetColumnCount(
            galleryWidth, minItemWidth: 220, spacing: 16, maxColumns: 6, itemCount: 7);

        Assert.Equal(expectedColumns, columns);
    }

    [Fact]
    public void SparseSearchResultsKeepTheResponsiveCardWidth()
    {
        const double galleryWidth = 1086;

        var columns = ResponsiveGalleryPanel.GetColumnCount(
            galleryWidth, minItemWidth: 220, spacing: 16, maxColumns: 6, itemCount: 1);

        Assert.Equal(4, columns);
    }

    [Theory]
    [InlineData(180, 320)]
    [InlineData(225, 400)]
    public void PosterFrameKeepsNineBySixteenRatio(double width, double expectedHeight)
    {
        Assert.Equal(expectedHeight, PortraitAspectFrame.GetHeightForWidth(width), precision: 6);
    }
}
