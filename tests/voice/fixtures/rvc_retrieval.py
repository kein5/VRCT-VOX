# SPDX-License-Identifier: MIT
# Exact retrieval try/except from RVC-Project/Retrieval-based-Voice-Conversion-WebUI
# 81eed5e8f68b6bed1789f682fe78cdd324495afc infer/rtrvc.py:250-280.
# Copyright (c) 2023 liujing04, 源文雨, Ftps. See integrations/rvc/LICENSE.upstream.
try:
    if hasattr(self, "index") and self.index_rate != 0:
        npy = feats[0][skip_head // 2 :].cpu().numpy().astype("float32")
        score, ix = self.index.search(npy, k=8)
        if (ix >= 0).all():
            weight = np.square(1 / score)
            weight /= weight.sum(axis=1, keepdims=True)
            npy = np.sum(
                self.big_npy[ix] * np.expand_dims(weight, axis=2), axis=1
            )
            if self.config.is_half:
                npy = npy.astype("float16")
            feats[0][skip_head // 2 :] = (
                torch.from_numpy(npy).unsqueeze(0).to(self.device)
                * self.index_rate
                + (1 - self.index_rate) * feats[0][skip_head // 2 :]
            )
        else:
            printt(
                i18n("索引无效：必须使用added_xxxx.index，不能使用trained_xxxx.index")
            )
    else:
        if report_status:
            printt(i18n("索引检索失败或未启用"))
except Exception:
    traceback.print_exc()
    printt(i18n("索引检索失败"))
