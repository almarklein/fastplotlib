from typing import *
from warnings import warn

import numpy as np

from .features._base import cleanup_slice

from pygfx import WorldObject, Group
from pygfx.linalg import Vector3

from .features import GraphicFeature, PresentFeature, GraphicFeatureIndexable

from abc import ABC, abstractmethod
from dataclasses import dataclass


PYGFX_EVENTS = [
    "key_down",
    "key_up",
    "pointer_down",
    "pointer_move",
    "pointer_up",
    "pointer_enter",
    "pointer_leave",
    "click",
    "double_click",
    "wheel",
    "close",
    "resize",
]


class BaseGraphic:
    def __init_subclass__(cls, **kwargs):
        """set the type of the graphic in lower case like "image", "line_collection", etc."""
        cls.type = cls.__name__\
            .lower()\
            .replace("graphic", "")\
            .replace("collection", "_collection")\
            .replace("stack", "_stack")

        super().__init_subclass__(**kwargs)


class Graphic(BaseGraphic):
    def __init__(
            self, name: str = None):
        """

        Parameters
        ----------
        name: str, optional
            name this graphic, makes it indexable within plots

        """

        self.name = name
        self.registered_callbacks = dict()
        self.present = PresentFeature(parent=self)

    @property
    def world_object(self) -> WorldObject:
        """Associated pygfx WorldObject."""
        return self._world_object

    @property
    def position(self) -> Vector3:
        """The position of the graphic. You can access or change
        using position.x, position.y, etc."""
        return self.world_object.position

    @property
    def visible(self) -> bool:
        """Access or change the visibility."""
        return self.world_object.visible

    @visible.setter
    def visible(self, v) -> bool:
        """Access or change the visibility."""
        self.world_object.visible = v

    @property
    def children(self) -> WorldObject:
        """Return the children of the WorldObject."""
        return self.world_object.children

    def __setattr__(self, key, value):
        if hasattr(self, key):
            attr = getattr(self, key)
            if isinstance(attr, GraphicFeature):
                attr._set(value)
                return

        super().__setattr__(key, value)

    def __repr__(self):
        rval = f"{self.__class__.__name__} @ {hex(id(self))}"
        if self.name is not None:
            return f"'{self.name}': {rval}"
        else:
            return rval


class Interaction(ABC):
    """Mixin class that makes graphics interactive"""
    @abstractmethod
    def _set_feature(self, feature: str, new_data: Any, indices: Any):
        pass

    @abstractmethod
    def _reset_feature(self, feature: str):
        pass

    def link(
            self,
            event_type: str,
            target: Any,
            feature: str,
            new_data: Any,
            callback: callable = None,
            bidirectional: bool = False
    ):
        """
        Link this graphic to another graphic upon an ``event_type`` to change the ``feature``
        of a ``target`` graphic.

        Parameters
        ----------
        event_type: str
            can be a pygfx event ("key_down", "key_up","pointer_down", "pointer_move", "pointer_up",
            "pointer_enter", "pointer_leave", "click", "double_click", "wheel", "close", "resize")
            or appropriate feature event (ex. colors, data, etc.) associated with the graphic (can use
            ``graphic_instance.feature_events`` to get a tuple of the valid feature events for the
            graphic)
        target: Any
            graphic to be linked to
        feature: str
            feature (ex. colors, data, etc.) of the target graphic that will change following
            the event
        new_data: Any
            appropriate data that will be changed in the feature of the target graphic after
            the event occurs
        callback: callable, optional
            user-specified callable that will handle event,
            the callable must take the following four arguments
            | ''source'' - this graphic instance
            | ''target'' - the graphic to be changed following the event
            | ''event'' - the ''pygfx event'' or ''feature event'' that occurs
            | ''new_data'' - the appropriate data of the ''target'' that will be changed
        bidirectional: bool, default False
            if True, the target graphic is also linked back to this graphic instance using the
            same arguments
            For example:
            .. code-block::python

        Returns
        -------
        None

        """
        if event_type in PYGFX_EVENTS:
            self.world_object.add_event_handler(self.event_handler, event_type)

        # make sure event is valid
        elif event_type in self.feature_events:
            if isinstance(self, GraphicCollection):
                feature_instance = getattr(self[:], event_type)
            else:
                feature_instance = getattr(self, event_type)

            feature_instance.add_event_handler(self._event_handler)

        else:
            raise ValueError(f"Invalid event, valid events are: {PYGFX_EVENTS + self.feature_events}")

        # make sure target feature is valid
        if feature is not None:
            if feature not in target.feature_events:
                raise ValueError(f"Invalid feature for target, valid features are: {target.feature_events}")

        if event_type not in self.registered_callbacks.keys():
            self.registered_callbacks[event_type] = list()

        callback_data = CallbackData(target=target, feature=feature, new_data=new_data, callback_function=callback)

        for existing_callback_data in self.registered_callbacks[event_type]:
            if existing_callback_data == callback_data:
                warn("linkage already exists for given event, target, and data, skipping")
                return

        self.registered_callbacks[event_type].append(callback_data)

        if bidirectional:
            target.link(
                event_type=event_type,
                target=self,
                feature=feature,
                new_data=new_data,
                callback=callback,
                bidirectional=False  # else infinite recursion, otherwise target will call
                                     # this instance .link(), and then it will happen again etc.
            )

    def _event_handler(self, event):
        """Handles the event after it occurs when two graphic have been linked together."""
        if event.type in self.registered_callbacks.keys():
            for target_info in self.registered_callbacks[event.type]:
                if target_info.callback_function is not None:
                    # if callback_function is not None, then callback function should handle the entire event
                    target_info.callback_function(source=self, target=target_info.target, event=event, new_data=target_info.new_data)

                elif isinstance(self, GraphicCollection):
                    # if target is a GraphicCollection, then indices will be stored in collection_index
                    if event.type in self.feature_events:
                        indices = event.pick_info["collection-index"]

                    # for now we only have line collections so this works
                    else:
                        for i, item in enumerate(self._graphics):
                            if item.world_object is event.pick_info["world_object"]:
                                indices = i
                    target_info.target._set_feature(feature=target_info.feature, new_data=target_info.new_data, indices=indices)
                else:
                    # if target is a single graphic, then indices do not matter
                    target_info.target._set_feature(feature=target_info.feature, new_data=target_info.new_data,
                                                    indices=None)


@dataclass
class CallbackData:
    """Class for keeping track of the info necessary for interactivity after event occurs."""
    target: Any
    feature: str
    new_data: Any
    callback_function: callable = None

    def __eq__(self, other):
        if not isinstance(other, CallbackData):
            raise TypeError("Can only compare against other <CallbackData> types")

        if other.target is not self.target:
            return False

        if not other.feature == self.feature:
            return False

        if not other.new_data == self.new_data:
            return False

        if (self.callback_function is None) and (other.callback_function is None):
            return True

        if other.callback_function is self.callback_function:
            return True

        else:
            return False


@dataclass
class PreviouslyModifiedData:
    """Class for keeping track of previously modified data at indices"""
    data: Any
    indices: Any


class GraphicCollection(Graphic):
    """Graphic Collection base class"""

    def __init__(self, name: str = None):
        super(GraphicCollection, self).__init__(name)
        self._graphics: List[Graphic] = list()

    @property
    def world_object(self) -> Group:
        """Returns the underling pygfx WorldObject."""
        return self._world_object

    @property
    def graphics(self) -> Tuple[Graphic]:
        """returns the Graphics within this collection"""
        return tuple(self._graphics)

    def add_graphic(self, graphic: Graphic, reset_index: True):
        """Add a graphic to the collection"""
        if not isinstance(graphic, self.child_type):
            raise TypeError(
                f"Can only add graphics of the same type to a collection, "
                f"You can only add {self.child_type} to a {self.__class__.__name__}, "
                f"you are trying to add a {graphic.__class__.__name__}."
            )
        self._graphics.append(graphic)
        if reset_index:
            self._reset_index()
        self.world_object.add(graphic.world_object)

    def remove_graphic(self, graphic: Graphic, reset_index: True):
        """Remove a graphic from the collection"""
        self._graphics.remove(graphic)
        if reset_index:
            self._reset_index()
        self.world_object.remove(graphic)

    def _reset_index(self):
        for new_index, graphic in enumerate(self._graphics):
            graphic.collection_index = new_index

    def __getitem__(self, key):
        if isinstance(key, int):
            key = [key]

        if isinstance(key, slice):
            key = cleanup_slice(key, upper_bound=len(self))
            selection_indices = range(key.start, key.stop, key.step)
            selection = self._graphics[key]

        # fancy-ish indexing
        elif isinstance(key, (tuple, list, np.ndarray)):
            if isinstance(key, np.ndarray):
                if not key.ndim == 1:
                    raise TypeError(f"{self.__class__.__name__} indexing supports "
                                    f"1D numpy arrays, int, slice, tuple or list of integers, "
                                    f"your numpy arrays has <{key.ndim}> dimensions.")
            selection = list()

            for ix in key:
                selection.append(self._graphics[ix])

            selection_indices = key
        else:
            raise TypeError(f"{self.__class__.__name__} indexing supports "
                            f"1D numpy arrays, int, slice, tuple or list of integers, "
                            f"you have passed a <{type(key)}>")

        return CollectionIndexer(
            parent=self,
            selection=selection,
            selection_indices=selection_indices
        )

    def __len__(self):
        return len(self._graphics)

    def __repr__(self):
        rval = super().__repr__()
        return f"{rval}\nCollection of <{len(self._graphics)}> Graphics"


class CollectionIndexer:
    """Collection Indexer"""
    def __init__(
            self,
            parent: GraphicCollection,
            selection: List[Graphic],
            selection_indices: Union[list, range],
    ):
        """

        Parameters
        ----------
        parent: GraphicCollection
            the GraphicCollection object that is being indexed
        selection: list of Graphics
            a list of the selected Graphics from the parent GraphicCollection based on the ``selection_indices``
        selection_indices: Union[list, range]
            the corresponding indices from the parent GraphicCollection that were selected
        """
        self._parent = parent
        self._selection = selection
        self._selection_indices = selection_indices

        # we use parent.graphics[0] instead of selection[0]
        # because the selection can be empty
        for attr_name in self._parent.graphics[0].__dict__.keys():
            attr = getattr(self._parent.graphics[0], attr_name)
            if isinstance(attr, GraphicFeature):
                collection_feature = CollectionFeature(
                    parent,
                    self._selection,
                    selection_indices=self._selection_indices,
                    feature=attr_name
                )
                collection_feature.__doc__ = f"indexable <{attr_name}> feature for collection"
                setattr(self, attr_name, collection_feature)

    @property
    def graphics(self) -> Tuple[Graphic]:
        """Returns a tuple of the selected graphics."""
        return tuple(self._selection)

    def __setattr__(self, key, value):
        if hasattr(self, key):
            attr = getattr(self, key)
            if isinstance(attr, CollectionFeature):
                attr._set(value)
                return

        super().__setattr__(key, value)

    def __len__(self):
        return len(self._selection)

    def __repr__(self):
        return f"{self.__class__.__name__} @ {hex(id(self))}\n" \
               f"Selection of <{len(self._selection)}> {self._selection[0].__class__.__name__}"


class CollectionFeature:
    """Collection Feature"""
    def __init__(
            self,
            parent: GraphicCollection,
            selection: List[Graphic],
            selection_indices,
            feature: str
    ):
        """
        parent: GraphicCollection
            GraphicCollection feature instance that is being indexed
        selection: list of Graphics
            a list of the selected Graphics from the parent GraphicCollection based on the ``selection_indices``
        selection_indices: Union[list, range]
            the corresponding indices from the parent GraphicCollection that were selected
        feature: str
            feature of Graphics in the GraphicCollection being indexed
        """
        self._selection = selection
        self._selection_indices = selection_indices
        self._feature = feature

        self._feature_instances: List[GraphicFeature] = list()

        if len(self._selection) > 0:
            for graphic in self._selection:
                fi = getattr(graphic, self._feature)
                self._feature_instances.append(fi)

            if isinstance(fi, GraphicFeatureIndexable):
                self._indexable = True
            else:
                self._indexable = False
        else:  # it's an empty selection so it doesn't really matter
            self._indexable = False

    def _set(self, value):
        self[:] = value

    def __getitem__(self, item):
        # only for indexable graphic features
        return [fi[item] for fi in self._feature_instances]

    def __setitem__(self, key, value):
        if self._indexable:
            for fi in self._feature_instances:
                fi[key] = value

        else:
            for fi in self._feature_instances:
                fi._set(value)

    def add_event_handler(self, handler: callable):
        """Adds an event handler to each of the selected Graphics from the parent GraphicCollection"""
        for fi in self._feature_instances:
            fi.add_event_handler(handler)

    def remove_event_handler(self, handler: callable):
        """Removes an event handler from each of the selected Graphics of the parent GraphicCollection"""
        for fi in self._feature_instances:
            fi.remove_event_handler(handler)

    def block_events(self, b: bool):
        """Blocks event handling from occurring."""
        for fi in self._feature_instances:
            fi.block_events(b)

    def __repr__(self):
        return f"Collection feature for: <{self._feature}>"
