# 標準RVCモデルのIVF検索欠落への対処（2026-10-30）

実機テストを長くしたところ、Saishoモデル/index・検索混合0.5で入力転送がvc_capture_overrunとなった。ミュート中の入力完了より前にワーカーは停止済みだった。旧の短い試験では変換開始直後に停止していたため未検出。

専用PipeWire・合成日本語入力で親のbinding/send/read/writeと子のconvert/検索/例外/GCを分離して計測した。binding約7.7ms、出力書込み約0.34ms、通常推論応答約21ms。問題の検索は正の距離・zero0、最大FLT_MAX、欠落ID=-1を返し、CheckedIndexが拒否してvc_index_failedとなった。終了時のgen2 GCは例外の後で、先行原因とは扱わない。

実indexはFAISS1.13.0のIndexIVFFlat、768次元、88,024vectors、2,257lists、nprobe1。[FAISS公式FAQ](https://github.com/facebookresearch/faiss/wiki/FAQ#what-does-it-mean-when-a-search-returns--1-ids)は、部分探索で候補数が足りない場合に-1を返し、nprobeで探索範囲と速度・精度の関係を調整すると説明する。[同様のRVC報告](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/issues/2864)も追跡したが、AI補助を明記した利用者報告であり、公式保証値や今回の原因の証拠として代用しない。imozuruの原文とmap/logはtmp/tts-latency-100/rvc-index-research/に保存。

変更はintegrations/rvc/loader.pyの初期化時のみ。実IVFをextract_index_ivfで取り出し、min(nlist,max(8,既存nprobe))をParameterSpaceで設定・読戻し確認。非IVFは変更なし。ファイルのモデル/indexは書き換えない。再試行・失敗無視・元音声へのfallbackは追加せず、8近傍のshape/有限正距離/ID範囲、80msブロック、160ms鮮度、Queue1の制約は維持する。8区画ですべての入力の候補充足や時間上限を保証するものではなく、未充足時は従来どおり停止する。

診断5はnprobeだけを8へ変更して273ブロック・約28秒のmute→resumeを処理しactive/errorなしで完了。人工の疎なIVFを使う実FAISS回帰5件も成功（旧1区画の欠落、補正後の8件取得、opaque wrapper、小さいnlist、大きい既存probe、Flatを確認）。新AppImage b8050d10のnative-rvc-fixed-strict-3は45.82秒でPASSし、全入力中のmute・Resume後の全入力・発声中停止・再起動OFFを確認。詳細数値はmodel-downloads-integration-report.md。

失敗native-guidance-rvc-strict-2、診断1〜4、nprobe8診断5を保持。これらは検証範囲と起動コードが異なり、診断成功を製品AppImage成功へ読み替えていない。製品修正・検証を既存担当44b1c384が読取り専用でレビューした。
