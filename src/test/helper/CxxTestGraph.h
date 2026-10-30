#ifndef CXX_TEST_GRAPH_H
#define CXX_TEST_GRAPH_H

#include <algorithm>
#include <string>
#include <vector>

#include "catch.hpp"

#include "Edge.h"
#include "NameHierarchy.h"
#include "StorageEdge.h"
#include "StorageNode.h"
#include "utilityString.h"

namespace cxx_test
{
inline std::vector<Id> findNodes(const std::vector<StorageNode>& nodes, const std::wstring& qualifiedName)
{
	std::vector<Id> ids;
	for (const StorageNode& node: nodes)
	{
		if (NameHierarchy::deserialize(node.serializedName).getQualifiedNameWithSignature() ==
			qualifiedName)
		{
			ids.push_back(node.id);
		}
	}
	return ids;
}

inline Id requireUniqueNode(const std::vector<StorageNode>& nodes, const std::wstring& qualifiedName)
{
	INFO("Expected exactly one symbol: " << utility::encodeToUtf8(qualifiedName));
	const std::vector<Id> ids = findNodes(nodes, qualifiedName);
	REQUIRE(ids.size() == 1);
	return ids.front();
}

inline bool hasEdge(const std::vector<StorageEdge>& edges, Edge::EdgeType type, Id source, Id target)
{
	return std::any_of(edges.begin(), edges.end(), [=](const StorageEdge& edge) {
		return edge.type == Edge::typeToInt(type) && edge.sourceNodeId == source &&
			edge.targetNodeId == target;
	});
}
}	 // namespace cxx_test

#endif	  // CXX_TEST_GRAPH_H
