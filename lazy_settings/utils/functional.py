from __future__ import annotations

import copy
import operator
from collections.abc import Callable, Iterator
from typing import Any, Generic, TypeVar, cast

empty: object = object()


_T = TypeVar("_T")
Wrapped = TypeVar("Wrapped")


def new_method_proxy(func: Callable[..., _T]) -> Callable[..., _T]:
    def inner(self, *args):
        if (_wrapped := self._wrapped) is empty:
            self._setup()
            _wrapped = self._wrapped
        return func(_wrapped, *args)

    inner._mask_wrapped = False  # type: ignore[attr-defined]
    return inner


def unpickle_lazyobject(wrapped: Wrapped) -> Wrapped:
    """
    Used to unpickle lazy objects. Just return its argument, which will be the
    wrapped object.
    """
    return wrapped


class LazyObject(Generic[Wrapped]):
    """
    A wrapper for another class that can be used to delay instantiation of the
    wrapped class.

    By subclassing, you have the opportunity to intercept and alter the
    instantiation. If you don't need to do that, use SimpleLazyObject.
    """

    # Avoid infinite recursion when tracing __init__ (#19456).
    _wrapped: Wrapped | None | object = None

    def __init__(self) -> None:
        # Note: if a subclass overrides __init__(), it will likely need to
        # override __copy__() and __deepcopy__() as well.
        self._wrapped = empty

    def __getattribute__(self, name: str) -> Any:
        if name == "_wrapped":
            # Avoid recursion when getting wrapped object.
            return super().__getattribute__(name)
        value = super().__getattribute__(name)
        # If attribute is a proxy method, raise an AttributeError to call
        # __getattr__() and use the wrapped object method.
        if not getattr(value, "_mask_wrapped", True):
            raise AttributeError
        return value

    __getattr__: Callable = new_method_proxy(getattr)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_wrapped":
            # Assign to __dict__ to avoid infinite __setattr__ loops.
            self.__dict__["_wrapped"] = value
        else:
            if self._wrapped is empty:
                self._setup()
            setattr(self._wrapped, name, value)

    def __delattr__(self, name: str) -> None:
        if name == "_wrapped":
            raise TypeError("can't delete _wrapped.")
        if self._wrapped is empty:
            self._setup()
        delattr(self._wrapped, name)

    def _setup(self) -> None:
        """
        Must be implemented by subclasses to initialize the wrapped object.
        """
        raise NotImplementedError(
            "subclasses of LazyObject must provide a _setup() method"
        )

    # Because we have messed with __class__ below, we confuse pickle as to what
    # class we are pickling. We're going to have to initialize the wrapped
    # object to successfully pickle it, so we might as well just pickle the
    # wrapped object since they're supposed to act the same way.
    #
    # Unfortunately, if we try to simply act like the wrapped object, the ruse
    # will break down when pickle gets our id(). Thus we end up with pickle
    # thinking, in effect, that we are a distinct object from the wrapped
    # object, but with the same __dict__. This can cause problems (see #25389).
    #
    # So instead, we define our own __reduce__ method and custom unpickler. We
    # pickle the wrapped object as the unpickler's argument, so that pickle
    # will pickle it normally, and then the unpickler simply returns its
    # argument.
    def __reduce__(self) -> tuple[Callable[[Wrapped], Wrapped], tuple[Wrapped]]:
        if self._wrapped is empty:
            self._setup()
        return (unpickle_lazyobject, (cast(Wrapped, self._wrapped),))

    def __copy__(self) -> "LazyObject | Wrapped":
        if self._wrapped is empty:
            # If uninitialized, copy the wrapper. Use type(self), not
            # self.__class__, because the latter is proxied.
            return type(self)()
        else:
            # If initialized, return a copy of the wrapped object.
            return copy.copy(self._wrapped)  # type: ignore[return-value]

    def __deepcopy__(self, memo: dict[int, Any]) -> "LazyObject | Wrapped":
        if self._wrapped is empty:
            # We have to use type(self), not self.__class__, because the
            # latter is proxied.
            result = type(self)()
            memo[id(self)] = result
            return result
        return copy.deepcopy(self._wrapped, memo)  # type: ignore[return-value]

    __bytes__: Callable[..., bytes] = new_method_proxy(bytes)
    __str__: Callable[..., str] = new_method_proxy(str)
    __bool__: Callable[..., bool] = new_method_proxy(bool)

    # Introspection support
    __dir__: Callable = new_method_proxy(dir)

    # Need to pretend to be the wrapped class, for the sake of objects that
    # care about this (especially in equality tests)
    __class__ = property(new_method_proxy(operator.attrgetter("__class__")))  # type: ignore[assignment]
    __eq__: Callable[..., bool] = new_method_proxy(operator.eq)
    __lt__: Callable[..., bool] = new_method_proxy(operator.lt)
    __gt__: Callable[..., bool] = new_method_proxy(operator.gt)
    __ne__: Callable[..., bool] = new_method_proxy(operator.ne)
    __hash__: Callable[..., int] = new_method_proxy(hash)

    # List/Tuple/Dictionary methods support
    __getitem__: Callable = new_method_proxy(operator.getitem)
    __setitem__: Callable[..., None] = new_method_proxy(operator.setitem)
    __delitem__: Callable[..., None] = new_method_proxy(operator.delitem)
    __iter__: Callable[..., Iterator] = new_method_proxy(iter)
    __len__: Callable[..., int] = new_method_proxy(len)
    __contains__: Callable[..., bool] = new_method_proxy(operator.contains)
