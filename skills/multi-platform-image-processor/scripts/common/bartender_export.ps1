param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [Parameter(Mandatory = $true)]
    [string]$Assembly,
    [int]$Width = 2400,
    [int]$Height = 2400
)

$ErrorActionPreference = "Stop"
Add-Type -Path $Assembly

$engine = $null
$document = $null
try {
    $engine = New-Object Seagull.BarTender.Print.Engine($true)
    $document = $engine.Documents.Open($Source)
    $resolution = New-Object Seagull.BarTender.Print.Resolution($Width, $Height)
    $document.ExportImageToFile(
        $Output,
        [Seagull.BarTender.Print.ImageType]::PNG,
        [Seagull.BarTender.Print.ColorDepth]::ColorDepth24bit,
        $resolution,
        [Seagull.BarTender.Print.OverwriteOptions]::Overwrite
    )
}
finally {
    if ($null -ne $document) {
        $document.Close([Seagull.BarTender.Print.SaveOptions]::DoNotSaveChanges)
    }
    if ($null -ne $engine) {
        $engine.Stop([Seagull.BarTender.Print.SaveOptions]::DoNotSaveChanges)
    }
}
