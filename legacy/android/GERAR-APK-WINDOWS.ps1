param([string]$AppUrl = "", [switch]$Bundle)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
# Download Gradle from its official server and validate SHA-256 before use.
$version='8.13'
$cache=Join-Path $PSScriptRoot '.gradle-dist'
$gradle=Join-Path $cache "gradle-$version\bin\gradle.bat"
if (-not (Test-Path $gradle)) {
    New-Item -ItemType Directory -Force $cache | Out-Null
    $archive=Join-Path $cache "gradle-$version-bin.zip"
    $url="https://services.gradle.org/distributions/gradle-$version-bin.zip"
    Invoke-WebRequest $url -OutFile $archive
    $expected=((Invoke-WebRequest "$url.sha256").Content).Trim().ToLower()
    $actual=(Get-FileHash $archive -Algorithm SHA256).Hash.ToLower()
    if($expected -ne $actual){Remove-Item $archive;throw 'Checksum Gradle incorreto. Download descartado.'}
    Expand-Archive $archive -DestinationPath $cache -Force
}
if(-not $env:ANDROID_HOME -and -not (Test-Path 'local.properties')){
    $sdk=Join-Path $env:LOCALAPPDATA 'Android\Sdk'
    if(Test-Path $sdk){$env:ANDROID_HOME=$sdk}else{throw 'Instale Android Studio + SDK 36. Abra o projeto Android e sincronize primeiro.'}
}
if(-not $env:JAVA_HOME){
    $jbr='C:\Program Files\Android\Android Studio\jbr'
    if(Test-Path $jbr){$env:JAVA_HOME=$jbr}else{throw 'Configure JAVA_HOME para JDK 17 ou superior, compatível com Gradle 8.13.'}
}
& $gradle --no-daemon wrapper --gradle-version $version --distribution-type bin
if($LASTEXITCODE -ne 0){throw 'Falha ao gerar wrapper Gradle.'}
$task=if($Bundle){'bundleRelease'}else{'assembleDebug'}
& $gradle --no-daemon $task "-PAPP_URL=$AppUrl"
if($LASTEXITCODE -ne 0){throw 'Build falhou. Leia o erro acima; nenhum APK válido foi confirmado.'}
Write-Host 'Saída em app\build\outputs. Debug não serve para envio à Play. AAB release ainda precisa da sua assinatura.'
