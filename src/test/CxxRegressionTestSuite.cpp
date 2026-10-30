#include "catch.hpp"

#include "language_packages.h"

#if BUILD_CXX_LANGUAGE_PACKAGE

#	include <algorithm>
#	include <memory>
#	include <set>
#	include <string>
#	include <vector>

#	include "CxxParser.h"
#	include "CxxTestGraph.h"
#	include "FilePathFilter.h"
#	include "FileRegister.h"
#	include "IndexerStateInfo.h"
#	include "IntermediateStorage.h"
#	include "ParserClientImpl.h"
#	include "TextAccess.h"

namespace
{
std::shared_ptr<IntermediateStorage> indexRegressionSource(
	const std::string& source, std::vector<std::wstring> flags = {})
{
	// Exercise the production parser, file registration, and graph recording together.
	const FilePath sourcePath = FilePath(L"cxx_regression.cpp").getCanonical();
	auto storage = std::make_shared<IntermediateStorage>();
	auto files = std::make_shared<FileRegister>(
		sourcePath, std::set<FilePath> {sourcePath}, std::set<FilePathFilter> {});
	CxxParser parser(
		std::make_shared<ParserClientImpl>(storage.get()),
		files,
		std::make_shared<IndexerStateInfo>());
	flags.push_back(L"-std=c++17");
	parser.buildIndex(sourcePath.wstr(), TextAccess::createFromString(source), std::move(flags));
	return storage;
}

bool hasTokenLocation(
	const IntermediateStorage& storage, Id node, size_t line, size_t startColumn, size_t endColumn)
{
	for (const StorageOccurrence& occurrence: storage.getStorageOccurrences())
	{
		if (occurrence.elementId != node)
		{
			continue;
		}
		for (const StorageSourceLocation& location: storage.getStorageSourceLocations())
		{
			if (location.id == occurrence.sourceLocationId && location.type == LOCATION_TOKEN &&
				location.startLine == line && location.endLine == line &&
				location.startCol == startColumn && location.endCol == endColumn)
			{
				return true;
			}
		}
	}
	return false;
}
}	 // namespace

TEST_CASE("cxx regression resolves calls to the correct overload", "[cxx][regression]")
{
	const auto storage = indexRegressionSource(
		"int select(int value) { return value; }\n"
		"double select(double value) { return value; }\n"
		"int use_integer() { return select(1); }\n"
		"double use_real() { return select(1.5); }\n");
	REQUIRE(storage->getErrors().empty());
	const auto& nodes = storage->getStorageNodes();
	const auto& edges = storage->getStorageEdges();
	const Id intOverload = cxx_test::requireUniqueNode(nodes, L"int select(int)");
	const Id doubleOverload = cxx_test::requireUniqueNode(nodes, L"double select(double)");
	const Id intCaller = cxx_test::requireUniqueNode(nodes, L"int use_integer()");
	const Id doubleCaller = cxx_test::requireUniqueNode(nodes, L"double use_real()");

	REQUIRE(cxx_test::hasEdge(edges, Edge::EDGE_CALL, intCaller, intOverload));
	REQUIRE(cxx_test::hasEdge(edges, Edge::EDGE_CALL, doubleCaller, doubleOverload));
	REQUIRE_FALSE(cxx_test::hasEdge(edges, Edge::EDGE_CALL, intCaller, doubleOverload));
	REQUIRE_FALSE(cxx_test::hasEdge(edges, Edge::EDGE_CALL, doubleCaller, intOverload));
}

TEST_CASE("cxx regression honors per-invocation preprocessor definitions", "[cxx][regression]")
{
	const std::string source =
		"#if FEATURE_ENABLED\n"
		"int enabled_value() { return 1; }\n"
		"#else\n"
		"int disabled_value() { return 0; }\n"
		"#endif\n";

	// Consecutive invocations must not leak macro definitions into each other.
	const auto enabled = indexRegressionSource(source, {L"-DFEATURE_ENABLED=1"});
	const auto disabled = indexRegressionSource(source, {L"-DFEATURE_ENABLED=0"});
	REQUIRE(enabled->getErrors().empty());
	REQUIRE(disabled->getErrors().empty());
	cxx_test::requireUniqueNode(enabled->getStorageNodes(), L"int enabled_value()");
	cxx_test::requireUniqueNode(disabled->getStorageNodes(), L"int disabled_value()");
	REQUIRE(cxx_test::findNodes(enabled->getStorageNodes(), L"int disabled_value()").empty());
	REQUIRE(cxx_test::findNodes(disabled->getStorageNodes(), L"int enabled_value()").empty());
}

TEST_CASE(
	"cxx regression merges declarations while retaining both source locations", "[cxx][regression]")
{
	const auto storage = indexRegressionSource(
		"int repeated(int value);\n"
		"int repeated(int value) { return value; }\n"
		"int run() { return repeated(3); }\n");
	REQUIRE(storage->getErrors().empty());
	const Id repeated = cxx_test::requireUniqueNode(
		storage->getStorageNodes(), L"int repeated(int)");
	const Id caller = cxx_test::requireUniqueNode(storage->getStorageNodes(), L"int run()");

	REQUIRE(hasTokenLocation(*storage, repeated, 1, 5, 12));
	REQUIRE(hasTokenLocation(*storage, repeated, 2, 5, 12));
	REQUIRE(cxx_test::hasEdge(storage->getStorageEdges(), Edge::EDGE_CALL, caller, repeated));
}

TEST_CASE(
	"cxx regression records diagnostics without contaminating the next parse", "[cxx][regression]")
{
	const auto broken = indexRegressionSource("int broken() { return unknown_symbol; }\n");
	REQUIRE_FALSE(broken->getErrors().empty());
	REQUIRE(std::any_of(
		broken->getErrors().begin(), broken->getErrors().end(), [](const StorageError& error) {
			return error.message.find(L"unknown_symbol") != std::wstring::npos;
		}));
	REQUIRE(std::any_of(
		broken->getStorageSourceLocations().begin(),
		broken->getStorageSourceLocations().end(),
		[](const StorageSourceLocation& location) {
			return location.type == LOCATION_ERROR && location.startLine == 1;
		}));

	const auto repaired = indexRegressionSource("int repaired() { return 42; }\n");
	REQUIRE(repaired->getErrors().empty());
	cxx_test::requireUniqueNode(repaired->getStorageNodes(), L"int repaired()");
	REQUIRE(cxx_test::findNodes(repaired->getStorageNodes(), L"int broken()").empty());
}

#endif	  // BUILD_CXX_LANGUAGE_PACKAGE
