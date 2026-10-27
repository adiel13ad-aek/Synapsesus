package app.synapse.discovery;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Message;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;
import androidx.webkit.WebViewAssetLoader;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Fixed-origin hybrid client. It never exposes a general JavaScript-to-native bridge.
 * External pages open in the device browser, not in the authenticated app WebView.
 * This source has NOT been built or device-tested in the artifact authoring environment.
 */
public final class MainActivity extends Activity {
    private static final int PICK_IMAGE = 11;
    private static final int SAVE_EXPORT = 12;
    private static final String DEMO_URL = "https://appassets.androidplatform.net/assets/index.html";
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private WebViewAssetLoader assets;
    private String startUrl;
    private boolean failed;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        startUrl = BuildConfig.APP_URL.isEmpty() ? DEMO_URL : BuildConfig.APP_URL + "/";
        assets = new WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this)).build();
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(250,249,254));
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(-1,-1));
        setContentView(root);
        // Target 36 enforces edge-to-edge. Keep controls outside status/navigation bars and IME.
        if (Build.VERSION.SDK_INT >= 30) {
            root.setOnApplyWindowInsetsListener((view,insets) -> {
                android.graphics.Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
                return WindowInsets.CONSUMED;
            });
        } else {
            root.setFitsSystemWindows(true);
        }
        web.setBackgroundColor(Color.rgb(250,249,254));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true); // user-selected image documents only; no broad storage permission
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setSupportMultipleWindows(true);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setUserAgentString(s.getUserAgentString() + " SynapseAndroid/0.4");
        if (Build.VERSION.SDK_INT >= 26) s.setSafeBrowsingEnabled(true);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (BuildConfig.APP_URL.isEmpty()) return assets.shouldInterceptRequest(request.getUrl());
                return null;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (sameOrigin(uri)) {
                    if ("/api/account/export".equals(uri.getPath())) { saveExport(); return true; }
                    return false;
                }
                if (request.isForMainFrame()) openExternal(uri);
                return true;
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                Toast.makeText(MainActivity.this,"Certificado HTTPS inválido. A conexão foi bloqueada.",Toast.LENGTH_LONG).show();
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && !failed) {
                    failed = true;
                    new AlertDialog.Builder(MainActivity.this).setTitle("Não foi possível conectar")
                        .setMessage("Confira sua conexão e se o servidor Synapse está online. Nenhum servidor público vem incluído no pacote.")
                        .setPositiveButton("Tentar novamente",(d,w)->{failed=false;web.loadUrl(startUrl);})
                        .setNegativeButton("Fechar",(d,w)->finish()).show();
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("image/*");
                pick.putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"image/jpeg","image/png","image/webp"});
                try { startActivityForResult(pick,PICK_IMAGE); }
                catch (RuntimeException e) { callback.onReceiveValue(null);fileCallback=null; }
                return true;
            }
            @Override public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {
                if (!isUserGesture) return false;
                WebView popup = new WebView(MainActivity.this);
                popup.setWebViewClient(new WebViewClient() {
                    @Override public boolean shouldOverrideUrlLoading(WebView child, WebResourceRequest request) {
                        Uri uri=request.getUrl();
                        // Even same-origin policy pages open externally; never transfer session cookies.
                        openExternal(uri);
                        child.post(child::destroy);
                        return true;
                    }
                });
                ((WebView.WebViewTransport)resultMsg.obj).setWebView(popup);
                resultMsg.sendToTarget();
                return true;
            }
        });
        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::goBack);
        }
        if (state == null || web.restoreState(state) == null) web.loadUrl(startUrl);
    }

    private boolean sameOrigin(Uri uri) {
        Uri base=Uri.parse(startUrl);
        return "https".equals(uri.getScheme()) && base.getHost()!=null && base.getHost().equals(uri.getHost())
            && normalizedPort(base)==normalizedPort(uri) && uri.getUserInfo()==null;
    }
    private int normalizedPort(Uri uri) { return uri.getPort()==-1?443:uri.getPort(); }
    private void openExternal(Uri uri) {
        if (!("https".equals(uri.getScheme())||"http".equals(uri.getScheme())) || uri.getHost()==null || uri.getUserInfo()!=null) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW,uri).addCategory(Intent.CATEGORY_BROWSABLE)); }
        catch (RuntimeException e) { Toast.makeText(this,"Nenhum navegador disponível.",Toast.LENGTH_SHORT).show(); }
    }
    private void goBack() {
        web.evaluateJavascript("typeof window.synapseBack === 'function' && window.synapseBack()",handled -> {
            if (!"true".equals(handled)) { if(web.canGoBack())web.goBack();else finish(); }
        });
    }
    @Override public void onBackPressed() { goBack(); }
    @Override protected void onSaveInstanceState(Bundle state) { web.saveState(state);super.onSaveInstanceState(state); }
    @Override protected void onPause() { super.onPause();web.onPause();CookieManager.getInstance().flush(); }
    @Override protected void onResume() { super.onResume();if(web!=null)web.onResume(); }
    @Override protected void onDestroy() { if(fileCallback!=null)fileCallback.onReceiveValue(null);if(web!=null)web.destroy();super.onDestroy(); }

    private void saveExport() {
        if (BuildConfig.APP_URL.isEmpty()) return;
        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/json");
        intent.putExtra(Intent.EXTRA_TITLE,"synapse-meus-dados.json");
        try { startActivityForResult(intent,SAVE_EXPORT); }
        catch(RuntimeException e) { Toast.makeText(this,"Gerenciador de arquivos indisponível.",Toast.LENGTH_LONG).show(); }
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request==PICK_IMAGE && fileCallback!=null) {
            Uri chosen=result==RESULT_OK&&data!=null?data.getData():null;
            if(chosen!=null&&!"content".equals(chosen.getScheme()))chosen=null;
            fileCallback.onReceiveValue(chosen==null?null:new Uri[]{chosen});fileCallback=null;
        }
        if(request==SAVE_EXPORT&&result==RESULT_OK&&data!=null&&data.getData()!=null) {
            Uri target=data.getData();
            if(!"content".equals(target.getScheme()))return;
            // Copy only this authenticated, fixed endpoint. Never forward cookies to arbitrary URLs.
            final String cookie=CookieManager.getInstance().getCookie(startUrl);
            new Thread(()->{
                HttpURLConnection c=null;
                try {
                    c=(HttpURLConnection)new URL(BuildConfig.APP_URL+"/api/account/export").openConnection();
                    c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(15000);
                    if(cookie!=null)c.setRequestProperty("Cookie",cookie);
                    if(c.getResponseCode()!=200)throw new java.io.IOException("Export failed");
                    try(InputStream in=c.getInputStream();OutputStream out=getContentResolver().openOutputStream(target,"wt")) {
                        if(out==null)throw new java.io.IOException("No output");
                        byte[] buffer=new byte[8192];int n;long total=0;
                        while((n=in.read(buffer))!=-1){total+=n;if(total>50L*1024*1024)throw new java.io.IOException("Export limit");out.write(buffer,0,n);}
                    }
                    runOnUiThread(()->Toast.makeText(this,"Cópia dos dados salva.",Toast.LENGTH_LONG).show());
                } catch(Exception e) {
                    runOnUiThread(()->Toast.makeText(this,"Falha ao salvar. Entre na conta e tente novamente; remova eventual arquivo incompleto.",Toast.LENGTH_LONG).show());
                } finally {if(c!=null)c.disconnect();}
            },"synapse-export").start();
        }
    }
}
