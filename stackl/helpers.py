class Helpers:
    _cache = {}

    @classmethod
    def cached(cls, key, scope=None, func=None):
        if scope is not None:
            if scope not in cls._cache:
                cls._cache[scope] = {}

            if key in cls._cache[scope]:
                return cls._cache[scope][key]
            else:
                result = None if func is None else func()
                cls._cache[scope][key] = result
                return result

        else:
            if key in cls._cache:
                return cls._cache[key]
            else:
                result = None if func is None else func()
                cls._cache[key] = result
                return result

    @classmethod
    def cache(cls, key, scope=None, object=None):
        if scope is not None:
            if scope not in cls._cache:
                cls._cache[scope] = {}

            cls._cache[scope][key] = object
        else:
            cls._cache[key] = object
