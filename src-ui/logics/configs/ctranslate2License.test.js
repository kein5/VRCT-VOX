import test from "node:test";
import assert from "node:assert/strict";
import { ctranslate2_weight_type_status } from "../ui_configs.js";
import { isNonCommercialWeight, needsLicenseConfirmation, weightRequest, weightIdOfRequest } from "./ctranslate2License.js";

const byId = Object.fromEntries(ctranslate2_weight_type_status.map(weight => [weight.id, weight]));

test("the default CTranslate2 weight is the MIT-licensed M2M100 418M", () => {
    const defaults = ctranslate2_weight_type_status.filter(weight => weight.is_default);
    assert.deepEqual(defaults.map(weight => weight.id), ["m2m100_418M-ct2-int8"]);
    assert.equal(isNonCommercialWeight(defaults[0]), false);
});

test("every weight states its license, and only NLLB is non-commercial", () => {
    for (const weight of ctranslate2_weight_type_status) {
        assert.ok(weight.license, `${weight.id} has no license`);
        assert.equal(isNonCommercialWeight(weight), weight.id.startsWith("nllb-"), weight.id);
        if (isNonCommercialWeight(weight)) assert.equal(weight.license, "CC-BY-NC-4.0");
    }
});

test("NLLB needs confirmation unless it is already the selected weight", () => {
    const nllb = byId["nllb-200-distilled-600M-ct2-int8"];
    assert.equal(needsLicenseConfirmation(nllb, "m2m100_418M-ct2-int8"), true);
    assert.equal(needsLicenseConfirmation(nllb, nllb.id), false);
    assert.equal(needsLicenseConfirmation(byId["m2m100_1.2B-ct2-int8"], "m2m100_418M-ct2-int8"), false);
});

test("the opt-in payload carries the flag, the plain payload stays a bare id", () => {
    assert.equal(weightRequest("m2m100_418M-ct2-int8"), "m2m100_418M-ct2-int8");
    const request = weightRequest("nllb-200-3.3B-ct2-int8", true);
    assert.deepEqual(request, { weight_type: "nllb-200-3.3B-ct2-int8", accept_non_commercial_license: true });
    assert.equal(weightIdOfRequest(request), "nllb-200-3.3B-ct2-int8");
    assert.equal(weightIdOfRequest("m2m100_418M-ct2-int8"), "m2m100_418M-ct2-int8");
});
