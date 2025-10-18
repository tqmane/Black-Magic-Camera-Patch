# Blackmagic Camera Mod – Customization Summary

## 概要
- ベース APK: `Blackmagic Camera_v3.0.2.0016(78)_antisplit.apk`
- 目的: Google Camera Engineering パッケージ名での動作、FileProvider 衝突回避、インストールエラー/クラッシュ修正、カメラ ID の制御。
- 作業環境: Windows 11、apktool 2.12.1、Android SDK build-tools 34.0.0。

## 主な変更点
1. **パッケージ/プロバイダ調整 (Manifest + smali)**
   - ルートパッケージ名を `com.google.android.GoogleCameraEng.blackmagic` に変更。
   - `AndroidManifest.xml` にて旧 FileProvider (`com.blackmagicdesign.android.camera.fileprovider`) と新 FileProvider の両方を登録。
   - `smali/com/blackmagicdesign/android/camera/domain/k.smali` および `smali/C5/o.smali` にフォールバック処理を追加し、FileProvider authority の不一致時に旧エントリへ切り替えるようガード。
2. **Camera Manager 関連改変**
   - `smali/com/blackmagicdesign/android/camera/manager/CameraManager$updateCameraList$1.smali` の ID フィルタを更新し、ID4 のみを除外しつつ、それ以外のロジカルカメラ (ID0〜ID3 など) をリスト化。
   - 非アクティブカメラ除去ロジックを確認し、`g` フラグ付きカメラを除外する仕様を維持。
3. **ネイティブライブラリの重複解消**
   - `decoded_apk/lib/**/*` を点検し、ビルド時に `libandroidx.graphics.path.so` が二重で取り込まれる問題を修正。
   - `decoded_apk/build` ディレクトリを再ビルド前にクリーン化する運用を確立。
4. **VerifyError root cause 修正**
   - `smali/com/blackmagicdesign/android/utils/j.smali` の `b(IIZ)` を、オリジナル APK の符号処理へ復元し、`VerifyError: bad type on operand stack` を解消。
   - LUT 同期ロジック (`smali/C5/o.smali`) と整合性を確認。
5. **その他の安定化施策**
   - `smali/com/blackmagicdesign/android/camera/domain/k.smali` の例外処理を強化し、FileProvider 失敗時のクラッシュを回避。
   - apktool 再ビルド後に `zipalign -p -f 4096` を適用した `dist/Blackmagic_Camera_mod_aligned.apk` を生成。

## 改変ファイル一覧（代表例）
| 区分 | ファイル | 目的 |
|------|----------|------|
| Manifest | `decoded_apk/AndroidManifest.xml` | パッケージ名と FileProvider authority の二重登録 |
| Java/Smali | `smali/com/blackmagicdesign/android/camera/domain/k.smali` | FileProvider フォールバックと例外ハンドリング |
| Java/Smali | `smali/C5/o.smali` | LUT インポート時の FileProvider authority フォールバック |
| Java/Smali | `smali/com/blackmagicdesign/android/camera/manager/CameraManager$updateCameraList$1.smali` | カメラ ID フィルタ (ID4 のみ除外) |
| Java/Smali | `smali/com/blackmagicdesign/android/utils/j.smali` | VerifyError の原因となったメソッドを復元 |
| Native libs | `decoded_apk/lib/**` | 重複ネイティブライブラリの整理 |
| Output | `dist/Blackmagic_Camera_mod_aligned.apk` | zipalign 済み最終成果物 |

## 作業フロー概要
1. **デコード & 初期調査**: apktool でデコードし、パッケージ名と FileProvider authority の衝突箇所を特定。
2. **Manifest/Smali 改変**: 新旧 authority 共存とフォールバック実装、Camera Manager のフィルタ改修、Utility クラス復元を実施。
3. **ネイティブライブラリ整備**: 重複ライブラリを排除し、ビルド前に `decoded_apk/build` を削除するフローを確立。
4. **ビルド & zipalign**: apktool で再ビルド後、Android build-tools 付属の `zipalign` で 4096 バイト境界に整列。
5. **実機検証**: 改変 APK を署名・インストールし、起動/録画の成功と Camera ID の挙動を確認。

## ビルド手順
```cmd
REM 1. 事前に build ディレクトリをクリーン
Remove-Item -Recurse -Force ".\decoded_apk\build" -ErrorAction SilentlyContinue

REM 2. apktool で再ビルド
apktool b ".\decoded_apk" ^
   -o ".\dist\Blackmagic_Camera_mod_unsigned.apk"

REM 3. zipalign で 4096 バイト境界に整列
"<ANDROID_SDK>\build-tools\34.0.0\zipalign" -p -f 4096 ^
   ".\dist\Blackmagic_Camera_mod_unsigned.apk" ^
   ".\dist\Blackmagic_Camera_mod_aligned.apk"
```
※ `<ANDROID_SDK>` はローカルにインストールした Android SDK のパスに置き換えてください。

## 署名
zipalign 済み APK に対して通常の keystore 署名を行ってください。例:
```cmd
apksigner sign --ks <your-keystore>.jks --out .\dist\Blackmagic_Camera_mod_signed.apk ^
   ".\dist\Blackmagic_Camera_mod_aligned.apk"
```
※ `apksigner` は Android SDK build-tools に付属します。

## CI / 自動化でAPK未解決になる場合の対処
GitHub Actions の自動実行で以下のエラーになる場合があります:

```
ERROR: APK path could not be resolved.
```

対処方法:
- ローカルに用意したAPKを使う: ワークフローの手動実行時に `fallback_apk` 入力でファイルパスを指定します。
- 直接URLを指定する: `fallback_apk_url` 入力に .apk または .apkm の直リンクを指定します。
- リポジトリ変数を使う: Settings → Variables and secrets → Repository variables で `FALLBACK_APK_URL` を作成し、有効なURLを設定します（手動入力が空のときに使用されます）。

補足:
- APKMirror が `.apkm` や `.xapk` のみを提供する場合、`.apkm` は自動で中から `.apk` を抽出します（`.xapk` も対応）。
- `force=false` の場合、APK が解決できないときは「更新なし」として終了し、CI が失敗しにくくなっています。
- 強制実行（`force=true`）時にAPK未解決だと失敗します。上記のいずれかの方法でAPKを供給してください。

### Downloader（APKMirror）の改善点
- `scripts/check_apkmirror.sh` が APKMirror のリリース→バリアント→ダウンロードの導線を解析し、見つかったURLから自動で `.apk` または `.apkm` を取得します。
- `.apkm` の場合は `scripts/extract_from_apkm.sh` により `base.apk` を抽出します。

## 検証状況
- VerifyError による起動クラッシュが解消されたことをログで確認。
- 起動および録画が可能であることを実機で確認（ユーザーレポート）。
- Camera ID4 のみを除外しているため、ID0〜ID3 の挙動は端末依存で確認を推奨。

## 既知の注意事項
- 追加で smali を変更する場合は、再度 `decoded_apk\build` のクリーンアップ後にビルドしてください。
- 署名済み APK を配布する際は、パッケージ名変更に伴うアプリ互換性に留意してください。
