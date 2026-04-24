param(
    [Parameter(Mandatory = $false)]
    [string]$Title = "IPv4",

    [Parameter(Mandatory = $true)]
    [string]$OldId,

    [Parameter(Mandatory = $false)]
    [string]$OutputRoot = (Join-Path -Path $PSScriptRoot -ChildPath "en.wikipedia.org"),

    [Parameter(Mandatory = $false)]
    [switch]$CleanOutput,

    [Parameter(Mandatory = $false)]
    [bool]$KeepArticleLinksOnline = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-WgetPath {
    $cmd = Get-Command "wget.exe" -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw "wget.exe not found. Install GNU Wget for Windows and re-run."
    }
    return $cmd.Source
}

function Update-ArticleLinksToOnline {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HtmlPath
    )

    $content = Get-Content -LiteralPath $HtmlPath -Raw

    $content = [regex]::Replace(
        $content,
        'href="(?:\./)?wiki/([^"]+)"',
        {
            param($m)
            $target = $m.Groups[1].Value
            "href=`"https://en.wikipedia.org/wiki/$target`""
        }
    )

    $content = [regex]::Replace(
        $content,
        'href="(?:\./)?w/index\.php\?title=([^"]+)"',
        {
            param($m)
            $target = $m.Groups[1].Value
            "href=`"https://en.wikipedia.org/w/index.php?title=$target`""
        }
    )

    Set-Content -LiteralPath $HtmlPath -Value $content -Encoding UTF8
}

if ($OldId -notmatch '^[0-9]+$') {
    throw "OldId must be numeric, for example 1348847330"
}

$encodedTitle = [uri]::EscapeDataString($Title)
$sourceUrl = "https://en.wikipedia.org/w/index.php?title=$encodedTitle&oldid=$OldId"
$wgetPath = Get-WgetPath

if ($CleanOutput -and (Test-Path -LiteralPath $OutputRoot)) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$wgetArgs = @(
    "--page-requisites",
    "--convert-links",
    "--adjust-extension",
    "--span-hosts",
    "--no-host-directories",
    "--restrict-file-names=windows",
    "--domains=en.wikipedia.org,upload.wikimedia.org,static.wikimedia.org,bits.wikimedia.org",
    "--directory-prefix=$OutputRoot",
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "$sourceUrl"
)

Write-Host "Mirroring $sourceUrl"
& $wgetPath @wgetArgs

$htmlFiles = Get-ChildItem -LiteralPath $OutputRoot -Recurse -File -Filter "*.html"
if ($htmlFiles.Count -eq 0) {
    throw "No HTML file was downloaded."
}

$mainHtml = $htmlFiles |
    Sort-Object FullName |
    Where-Object { $_.FullName -match "index\.php" } |
    Select-Object -First 1

if ($null -eq $mainHtml) {
    $mainHtml = $htmlFiles | Sort-Object Length -Descending | Select-Object -First 1
}

$wikiDir = Join-Path -Path $OutputRoot -ChildPath "wiki"
New-Item -ItemType Directory -Path $wikiDir -Force | Out-Null

$articleHtml = Join-Path -Path $wikiDir -ChildPath "$Title.html"
Copy-Item -LiteralPath $mainHtml.FullName -Destination $articleHtml -Force

$indexHtml = @"
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>$Title - Local Wikipedia Mirror</title>
  <meta http-equiv="refresh" content="0; url=./wiki/$Title.html">
</head>
<body>
  <p>Opening local mirror: <a href="./wiki/$Title.html">$Title</a></p>
</body>
</html>
"@

Set-Content -LiteralPath (Join-Path -Path $OutputRoot -ChildPath "index.html") -Value $indexHtml -Encoding UTF8

if ($KeepArticleLinksOnline) {
    Update-ArticleLinksToOnline -HtmlPath $articleHtml
}

$robotsPath = Join-Path -Path $OutputRoot -ChildPath "robots.txt"
if (-not (Test-Path -LiteralPath $robotsPath)) {
    Set-Content -LiteralPath $robotsPath -Value "User-agent: *`nDisallow:" -Encoding ASCII
}

Write-Host "Done."
Write-Host "Open: $articleHtml"
Write-Host "Serve locally from: $OutputRoot"
Write-Host "Example: py -m http.server 8080"
