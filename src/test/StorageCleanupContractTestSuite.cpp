#include "catch.hpp"

#include <QTemporaryDir>

#include "Edge.h"
#include "FilePath.h"
#include "LocationType.h"
#include "NodeKind.h"
#include "SqliteIndexStorage.h"

namespace
{
class CleanupDatabase
{
public:
	CleanupDatabase()
		: storage(FilePath(directory.path().toStdWString() + L"/cleanup.sqlite"))
	{
		REQUIRE(directory.isValid());
		storage.setup();
		storage.setMode(SqliteIndexStorage::STORAGE_MODE_CLEAR);
	}

	Id file(const std::wstring& name)
	{
		const Id id = storage.addNode(StorageNodeData(nodeKindToInt(NODE_FILE), name));
		REQUIRE(storage.addFile(StorageFile(id, name, L"cpp", "", true, true)));
		return id;
	}

	Id node(const std::wstring& name)
	{
		return storage.addNode(StorageNodeData(nodeKindToInt(NODE_SYMBOL), name));
	}

	Id edge(Id source, Id target, Edge::EdgeType type = Edge::EDGE_MEMBER)
	{
		return storage.addEdge(StorageEdgeData(Edge::typeToInt(type), source, target));
	}

	void occurrence(Id element, Id file, size_t line)
	{
		const Id location = storage.addSourceLocation(
			StorageSourceLocationData(file, line, 1, line, 2, locationTypeToInt(LOCATION_TOKEN)));
		REQUIRE(storage.addOccurrence(StorageOccurrence(element, location)));
	}

	void clear(const std::vector<Id>& files)
	{
		storage.beginTransaction();
		storage.removeElementsWithLocationInFiles(files, nullptr);
		storage.removeElements(files);
		storage.commitTransaction();
	}

	// The database closes before QTemporaryDir removes its directory.
	QTemporaryDir directory;
	SqliteIndexStorage storage;
};
} // namespace

TEST_CASE(
	"storage cleanup preserves membership between surviving symbols",
	"[contract][storage-cleanup]")
{
	// GRAPH-001 / RELATION-001: a reference to a namespace in a deleted translation unit
	// must not remove membership facts declared in surviving headers and source files.
	CleanupDatabase db;
	const Id removed = db.file(L"obsolete.cpp");
	const Id retained = db.file(L"api.h");
	const Id parent = db.node(L"toy");
	const Id child = db.node(L"toy::answer");
	const Id member = db.edge(parent, child);
	db.occurrence(parent, removed, 1);
	db.occurrence(parent, retained, 1);
	db.occurrence(child, retained, 2);
	REQUIRE(db.storage.getOccurrencesForElementIds({member}).empty());

	db.clear({removed});

	REQUIRE(db.storage.isNode(parent));
	REQUIRE(db.storage.isNode(child));
	REQUIRE(db.storage.isEdge(member));
	REQUIRE(db.storage.getEdgeById(member).sourceNodeId == parent);
	REQUIRE(db.storage.getEdgeById(member).targetNodeId == child);
	REQUIRE_FALSE(db.storage.isFile(removed));
}

TEST_CASE(
	"storage cleanup does not preserve a deleted child through membership",
	"[contract][storage-cleanup]")
{
	CleanupDatabase db;
	const Id removed = db.file(L"obsolete.cpp");
	const Id retained = db.file(L"api.h");
	const Id parent = db.node(L"toy");
	const Id child = db.node(L"toy::obsolete");
	const Id member = db.edge(parent, child);
	db.occurrence(parent, removed, 1);
	db.occurrence(parent, retained, 1);
	db.occurrence(child, removed, 2);

	db.clear({removed});

	REQUIRE(db.storage.isNode(parent));
	REQUIRE_FALSE(db.storage.isNode(child));
	REQUIRE_FALSE(db.storage.isEdge(member));
}

TEST_CASE(
	"storage cleanup removes membership when its parent disappears",
	"[contract][storage-cleanup]")
{
	CleanupDatabase db;
	const Id removed = db.file(L"obsolete.cpp");
	const Id retained = db.file(L"other.cpp");
	const Id parent = db.node(L"obsolete_parent");
	const Id child = db.node(L"retained_child");
	const Id member = db.edge(parent, child);
	db.occurrence(parent, removed, 1);
	db.occurrence(child, retained, 1);

	db.clear({removed});

	REQUIRE_FALSE(db.storage.isNode(parent));
	REQUIRE(db.storage.isNode(child));
	REQUIRE_FALSE(db.storage.isEdge(member));
}

TEST_CASE(
	"storage cleanup checks survival outside the entire cleared file set",
	"[contract][storage-cleanup]")
{
	CleanupDatabase db;
	const Id firstRemoved = db.file(L"first.cpp");
	const Id secondRemoved = db.file(L"second.cpp");
	const Id retained = db.file(L"api.h");
	const Id parent = db.node(L"toy");
	const Id keptChild = db.node(L"toy::kept");
	const Id removedChild = db.node(L"toy::removed");
	const Id keptMember = db.edge(parent, keptChild);
	const Id removedMember = db.edge(parent, removedChild);
	db.occurrence(parent, firstRemoved, 1);
	db.occurrence(parent, retained, 1);
	db.occurrence(keptChild, firstRemoved, 2);
	db.occurrence(keptChild, retained, 2);
	db.occurrence(removedChild, firstRemoved, 3);
	db.occurrence(removedChild, secondRemoved, 3);

	db.clear({firstRemoved, secondRemoved});

	REQUIRE(db.storage.isEdge(keptMember));
	REQUIRE(db.storage.isNode(keptChild));
	REQUIRE_FALSE(db.storage.isEdge(removedMember));
	REQUIRE_FALSE(db.storage.isNode(removedChild));
}

TEST_CASE(
	"storage cleanup retains existing cleanup for nonmember relationships",
	"[contract][storage-cleanup]")
{
	CleanupDatabase db;
	const Id removed = db.file(L"obsolete.cpp");
	const Id retained = db.file(L"remaining.cpp");
	const Id source = db.node(L"source");
	const Id target = db.node(L"target");
	const Id call = db.edge(source, target, Edge::EDGE_CALL);
	db.occurrence(source, removed, 1);
	db.occurrence(source, retained, 1);
	db.occurrence(target, retained, 2);

	db.clear({removed});

	REQUIRE(db.storage.isNode(source));
	REQUIRE(db.storage.isNode(target));
	REQUIRE_FALSE(db.storage.isEdge(call));
}

TEST_CASE(
	"storage cleanup still removes edges with explicit occurrences in cleared files",
	"[contract][storage-cleanup]")
{
	CleanupDatabase db;
	const Id removed = db.file(L"obsolete.cpp");
	const Id retained = db.file(L"api.h");
	const Id parent = db.node(L"toy");
	const Id child = db.node(L"toy::answer");
	const Id member = db.edge(parent, child);
	db.occurrence(parent, removed, 1);
	db.occurrence(parent, retained, 1);
	db.occurrence(child, retained, 2);
	db.occurrence(member, removed, 2);

	db.clear({removed});

	REQUIRE(db.storage.isNode(parent));
	REQUIRE(db.storage.isNode(child));
	REQUIRE_FALSE(db.storage.isEdge(member));
}
