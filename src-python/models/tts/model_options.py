"""Bounded synthesis capabilities from speech.cpp's model information."""
SAFE_SEED_MAX = 9007199254740991


def parse_options(document):
    if not isinstance(document, dict) or not isinstance(document.get('data'), list) or len(document['data']) > 32:
        raise ValueError('invalid_catalog')
    models = []
    for row in document['data']:
        if not isinstance(row, dict) or not isinstance(row.get('speech'), dict):
            raise ValueError('invalid_model')
        speech = row['speech']
        if speech.get('task') != 'synthesis':
            continue
        if (not isinstance(row.get('id'), str) or not 0 < len(row['id']) <= 512
                or not isinstance(speech.get('options'), list) or len(speech['options']) > 128):
            raise ValueError('invalid_options')
        result = dict(model=row['id'], seed=None, instructions=False)
        seen = set()
        for option in speech['options']:
            if not isinstance(option, dict) or not isinstance(option.get('name'), str):
                raise ValueError('invalid_option')
            name = option['name']
            if name in seen:
                raise ValueError('duplicate_option')
            seen.add(name)
            if name == 'seed' and option.get('type') == 'int':
                lo, hi = option.get('minimum', 0), option.get('maximum', SAFE_SEED_MAX)
                if type(lo) is not int or type(hi) is not int or lo > hi:
                    raise ValueError('invalid_seed_range')
                lo, hi = max(0, lo), min(SAFE_SEED_MAX, hi)
                if lo <= hi:
                    result['seed'] = dict(minimum=lo, maximum=hi)
            if name == 'instructions' and option.get('type') == 'string':
                result['instructions'] = True
        models.append(result)
    if len(models) != 1:
        raise ValueError('synthesis_model_ambiguous')
    return models[0]
