"""Validate explicitly configured, entry-frozen engine state without changing old seeds."""
from dataclasses import asdict, replace
from config.engine_parameters import encode, normalize, revision


def stamp(seed, strategy):
    token=getattr(strategy,'_configuration_revision',None)
    if token:
        seed={**seed,'configured_revision':token}
        seed['configured_digest']=revision(seed)
    return seed


def valid(seed, expected, default_config):
    if seed==expected:return True
    if not isinstance(seed,dict) or not seed.get('configured_revision'):return False
    content={k:v for k,v in seed.items() if k!='configured_digest'}
    if seed.get('configured_digest')!=revision(content):return False
    plain={k:v for k,v in content.items() if k!='configured_revision'}
    try:
        raw=plain['config'];defaults=asdict(default_config)
        if set(raw)!=set(defaults):return False
        values=normalize(raw,defaults)
        replace(default_config,**values)
        return {**plain,'config':expected['config']}==expected
    except (ValueError,TypeError,KeyError):return False
