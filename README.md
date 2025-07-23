# 社内チェック業務 BPR分析ツール

このツールは、社内チェック業務のBPR（ビジネスプロセス・リエンジニアリング）を分析するためのStreamlitアプリケーションです。

## 必要なファイル

アプリケーションの実行には、以下の2つのCSVファイルが必要です。

- `制作物一覧 CSV`
- `ヘッダー一覧 CSV`

これらのファイルは、アプリケーションのサイドバーからアップロードしてください。

## 実行方法

### ローカルでの実行

1.  **リポジトリをクローンします。**

    ```bash
    git clone <このリポジトリのURL>
    cd 社内チェック出しツール
    ```

2.  **仮想環境を作成し、アクティベートします。**

    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **必要なライブラリをインストールします。**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Streamlitアプリケーションを起動します。**

    ```bash
    streamlit run main.py
    ```

    ブラウザでアプリケーションが開きます。

### Streamlit Cloudでのデプロイ

1.  このリポジトリをGitHubにプッシュします。
2.  [Streamlit Cloud](https://share.streamlit.io/) にアクセスし、GitHubリポジトリを接続してデプロイします。
    - `main.py` をメインファイルとして指定します。
    - Pythonのバージョンは、Streamlit Cloudが推奨するバージョンを選択してください。

## ファイル構成

- `main.py`: Streamlitアプリケーションのメインスクリプト
- `requirements.txt`: Pythonの依存関係リスト
- `.streamlit/config.toml`: Streamlitの設定ファイル
- `Procfile`: Herokuなどのプラットフォームでのデプロイ用
- `setup.sh`: デプロイ時のセットアップスクリプト
- `README.md`: この説明ファイル
