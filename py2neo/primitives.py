#!/usr/bin/env python
# -*- encoding: utf-8 -*-

# Copyright 2011-2015, Nigel Small
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from datetime import date, time, datetime
from decimal import Decimal

from py2neo.compat import integer, string
from py2neo.util import ustr


__all__ = ["GraphView", "Node", "Relationship"]


# Maximum and minimum integers supported up to Java 7.
# Java 8 also supports unsigned long which can extend
# to (2 ** 64 - 1) but Neo4j is not yet on Java 8.
JAVA_INTEGER_MIN_VALUE = -2 ** 63
JAVA_INTEGER_MAX_VALUE = 2 ** 63 - 1


def cast_property(value):
    """ Cast the supplied property value to something supported by
    Neo4j, raising an error if this is not possible.
    """
    if isinstance(value, (bool, float)):
        pass
    elif isinstance(value, integer):
        if JAVA_INTEGER_MIN_VALUE <= value <= JAVA_INTEGER_MAX_VALUE:
            pass
        else:
            raise ValueError("Integer value out of range: %s" % value)
    elif isinstance(value, string):
        value = ustr(value)
    elif isinstance(value, (frozenset, list, set, tuple)):
        # check each item and all same type
        list_value = []
        list_type = None
        for item in value:
            item = cast_property(item)
            if list_type is None:
                list_type = type(item)
                if list_type is list:
                    raise ValueError("Lists cannot contain nested collections")
            elif not isinstance(item, list_type):
                raise TypeError("List property items must be of similar types")
            list_value.append(item)
        value = list_value
    elif isinstance(value, (datetime, date, time)):
        value = value.isoformat()
    elif isinstance(value, Decimal):
        # We'll lose some precision here but Neo4j can't
        # handle decimals anyway.
        value = float(value)
    elif isinstance(value, complex):
        value = [value.real, value.imag]
    else:
        raise TypeError("Invalid property type: %s" % type(value))
    return value


class PropertySet(dict):
    """ A dict subclass that equates None with a non-existent key.
    """

    def __init__(self, iterable=None, **kwargs):
        dict.__init__(self)
        self.update(iterable, **kwargs)

    def __eq__(self, other):
        if not isinstance(other, PropertySet):
            other = PropertySet(other)
        return dict.__eq__(self, other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        value = 0
        for key, value in self.items():
            if isinstance(value, list):
                value ^= hash((key, tuple(value)))
            else:
                value ^= hash((key, value))
        return value

    def __getitem__(self, key):
        return dict.get(self, key)

    def __setitem__(self, key, value):
        if value is None:
            try:
                dict.__delitem__(self, key)
            except KeyError:
                pass
        else:
            dict.__setitem__(self, key, cast_property(value))

    def replace(self, iterable=None, **kwargs):
        self.clear()
        self.update(iterable, **kwargs)

    def setdefault(self, key, default=None):
        if key in self:
            value = self[key]
        elif default is None:
            value = None
        else:
            value = dict.setdefault(self, key, default)
        return value

    def update(self, iterable=None, **kwargs):
        for key, value in dict(iterable or {}, **kwargs).items():
            self[key] = value


class PropertyContainer(object):
    """ Base class for objects that contain a set of properties,
    """

    def __init__(self, **properties):
        self.properties = PropertySet(properties)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(id(self))

    def __contains__(self, key):
        return key in self.properties

    def __getitem__(self, key):
        return self.properties.__getitem__(key)

    def __setitem__(self, key, value):
        self.properties.__setitem__(key, value)

    def __delitem__(self, key):
        self.properties.__delitem__(key)

    def __iter__(self):
        raise TypeError("%r object is not iterable" % self.__class__.__name__)


class EntitySetView(object):

    def __init__(self, collection):
        self._entities = collection

    def __eq__(self, other):
        return frozenset(self) == frozenset(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __len__(self):
        return len(self._entities)

    def __iter__(self):
        return iter(self._entities)

    def __contains__(self, item):
        return item in self._entities

    def __or__(self, other):
        return EntitySetView(frozenset(self).union(other))

    def __and__(self, other):
        return EntitySetView(frozenset(self).intersection(other))

    def __sub__(self, other):
        return EntitySetView(frozenset(self).difference(other))

    def __xor__(self, other):
        return EntitySetView(frozenset(self).symmetric_difference(other))


class GraphView(object):

    def __init__(self, nodes, relationships):
        self.nodes = EntitySetView(frozenset(nodes))
        self.relationships = EntitySetView(frozenset(relationships))
        self.order = len(self.nodes)
        self.size = len(self.relationships)

    def __repr__(self):
        return "<GraphView order=%s size=%s>" % (self.order, self.size)

    def __eq__(self, other):
        try:
            return self.nodes == other.nodes and self.relationships == other.relationships
        except AttributeError:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        value = 0
        for entity in self.nodes:
            value ^= hash(entity)
        for entity in self.relationships:
            value ^= hash(entity)
        return value

    def __len__(self):
        return len(self.relationships)

    def __iter__(self):
        return iter(self.relationships)

    def __bool__(self):
        return bool(self.relationships)

    def __nonzero__(self):
        return bool(self.relationships)

    def __or__(self, other):
        return GraphView(self.nodes | other.nodes, self.relationships | other.relationships)

    def __and__(self, other):
        return GraphView(self.nodes & other.nodes, self.relationships & other.relationships)

    def __sub__(self, other):
        relationships = self.relationships - other.relationships
        nodes = (self.nodes - other.nodes) | set().union(*(rel.nodes for rel in relationships))
        return GraphView(nodes, relationships)

    def __xor__(self, other):
        relationships = self.relationships ^ other.relationships
        nodes = (self.nodes ^ other.nodes) | set().union(*(rel.nodes for rel in relationships))
        return GraphView(nodes, relationships)

    @property
    def property_keys(self):
        keys = set()
        for entity in self.nodes:
            keys |= set(entity.properties.keys())
        for entity in self.relationships:
            keys |= set(entity.properties.keys())
        return frozenset(keys)

    @property
    def labels(self):
        return frozenset().union(*(node.labels for node in self.nodes))

    @property
    def types(self):
        return frozenset(relationship.type for relationship in self.relationships)


class Node(PropertyContainer, GraphView):

    def __init__(self, *labels, **properties):
        PropertyContainer.__init__(self, **properties)
        self.__labels = set(labels)
        GraphView.__init__(self, [self], [])

    def __repr__(self):
        return "<Node labels=%r properties=%r>" % (set(self.labels), self.properties)

    def __eq__(self, other):
        try:
            return self is other
        except AttributeError:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(id(self))

    def __len__(self):
        return 0

    def __iter__(self):
        return iter([])

    @property
    def labels(self):
        return self.__labels


class Relationship(PropertyContainer, GraphView):

    def __init__(self, *args, **properties):
        PropertyContainer.__init__(self, **properties)
        num_args = len(args)
        if num_args == 0:
            self.endpoints = (None, None)
            self.type = None
        elif num_args == 1:
            self.endpoints = (None, None)
            self.type = args[0]
        elif num_args == 2:
            self.endpoints = args
            self.type = None
        else:
            self.endpoints = (args[0],) + args[2:]
            self.type = args[1]
        GraphView.__init__(self, self.endpoints, [self])

    def __repr__(self):
        return "<Relationship endpoints=%r type=%r properties=%r>" % \
               (self.endpoints, self.type, self.properties)

    def __eq__(self, other):
        try:
            return self is other
        except AttributeError:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(id(self))

    def __len__(self):
        return 1

    def __iter__(self):
        yield self

    @property
    def start(self):
        return self.endpoints[0]

    @property
    def end(self):
        return self.endpoints[-1]
