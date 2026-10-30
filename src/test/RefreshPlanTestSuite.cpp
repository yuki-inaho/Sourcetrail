#include "catch.hpp"

#include <algorithm>
#include <array>
#include <map>
#include <utility>
#include <vector>

#include "RefreshPlan.h"

namespace
{
using Paths = RefreshPlan::FilePaths;
using Dependencies = std::vector<std::pair<FilePath, FilePath>>;

// FilePath::operator== consults the filesystem. Match the planner's ordered-set identity
// instead so these symbolic fixtures neither need nor inspect real files.
bool samePaths(const Paths& left, const Paths& right)
{
	return left.size() == right.size() &&
		std::equal(left.begin(), left.end(), right.begin(), [](const FilePath& a, const FilePath& b) {
			   return !(a < b) && !(b < a);
		   });
}

// Query test graphs by traversal, like a storage adapter. The exhaustive oracle below uses
// a different representation and algorithm (a Boolean matrix and Warshall closure).
Paths reachable(const Dependencies& edges, const Paths& seeds, bool reverse)
{
	std::map<FilePath, Paths> adjacency;
	for (const auto& edge: edges)
	{
		adjacency[reverse ? edge.second : edge.first].insert(reverse ? edge.first : edge.second);
	}
	Paths result;
	Paths pending = seeds;
	Paths visited;
	while (!pending.empty())
	{
		const FilePath path = *pending.begin();
		pending.erase(pending.begin());
		visited.insert(path);
		for (const FilePath& target: adjacency[path])
		{
			result.insert(target);
			if (visited.find(target) == visited.end())
			{
				pending.insert(target);
			}
		}
	}
	return result;
}

RefreshPlan planFor(
	const Paths& sources,
	const Paths& unchanged,
	const Paths& changed,
	const Dependencies& includes,
	const Dependencies& imports = {})
{
	auto query = [&](const Paths& seeds, bool reverse) {
		Paths result = reachable(includes, seeds, reverse);
		const Paths imported = reachable(imports, seeds, reverse);
		result.insert(imported.begin(), imported.end());
		return result;
	};
	return RefreshPlan::forUpdatedFiles(
		sources,
		unchanged,
		changed,
		[&](const Paths& seeds) { return query(seeds, false); },
		[&](const Paths& seeds) { return query(seeds, true); });
}

Paths pathsForMask(unsigned int mask, const std::array<FilePath, 3>& files)
{
	Paths result;
	for (size_t i = 0; i < files.size(); ++i)
	{
		if (mask & (1u << i))
		{
			result.insert(files[i]);
		}
	}
	return result;
}
}	 // namespace

TEST_CASE("refresh contract preserves shared dependencies of static sources", "[contract][refresh]")
{
	// REFRESH-002: a private dependency is cleaned, a shared dependency is preserved.
	const FilePath edited(L"edited.cpp");
	const FilePath stable(L"stable.cpp");
	const FilePath shared(L"shared.h");
	const FilePath privateHeader(L"private.h");
	const FilePath nested(L"nested.h");
	const Dependencies dependencies = {
		{edited, shared}, {stable, shared}, {edited, privateHeader}, {privateHeader, nested}};
	const RefreshPlan plan = planFor({edited, stable}, {stable}, {edited}, dependencies);
	REQUIRE(samePaths(plan.filesToClear, {edited, privateHeader, nested}));
	REQUIRE(samePaths(plan.filesToIndex, {edited}));
}

TEST_CASE("refresh contract propagates changes through dependency cycles", "[contract][refresh]")
{
	const FilePath first(L"first.cpp");
	const FilePath second(L"second.cpp");
	const FilePath header(L"header.h");
	const Dependencies dependencies = {{first, header}, {second, header}, {header, header}};
	const RefreshPlan plan = planFor({first, second}, {first, second}, {header}, dependencies);
	REQUIRE(samePaths(plan.filesToClear, {first, second, header}));
	REQUIRE(samePaths(plan.filesToIndex, {first, second}));
}

TEST_CASE(
	"refresh contract indexes new sources and only clears removed sources", "[contract][refresh]")
{
	const FilePath stable(L"stable.cpp");
	const FilePath added(L"added.cpp");
	const FilePath removed(L"removed.cpp");
	const RefreshPlan plan = planFor({stable, added}, {stable}, {removed}, {});
	REQUIRE(samePaths(plan.filesToClear, {removed}));
	REQUIRE(samePaths(plan.filesToIndex, {added}));

	const RefreshPlan noChanges = planFor({stable}, {stable}, {}, {});
	REQUIRE(noChanges.filesToClear.empty());
	REQUIRE(noChanges.filesToIndex.empty());
}

TEST_CASE("refresh contract preserves separate include and import closures", "[contract][refresh]")
{
	// Characterize the current storage adapter: paths cannot alternate relation kinds.
	const FilePath source(L"source.cpp");
	const FilePath bridge(L"bridge.h");
	const FilePath imported(L"module.py");
	const RefreshPlan plan = planFor(
		{source}, {source}, {imported}, {{source, bridge}}, {{bridge, imported}});
	REQUIRE(samePaths(plan.filesToClear, {bridge, imported}));
	REQUIRE(plan.filesToIndex.empty());
}

TEST_CASE("refresh contract retains dependency query inputs and order", "[contract][refresh]")
{
	const FilePath changed(L"changed.cpp");
	const FilePath staticSource(L"static.cpp");
	const FilePath dependent(L"dependent.cpp");
	std::vector<std::pair<char, Paths>> calls;
	const RefreshPlan plan = RefreshPlan::forUpdatedFiles(
		{changed, staticSource, dependent},
		{staticSource, dependent},
		{changed},
		[&](const Paths& seeds) {
			calls.emplace_back('F', seeds);
			return Paths();
		},
		[&](const Paths& seeds) {
			calls.emplace_back('R', seeds);
			return Paths {dependent};
		});
	REQUIRE(calls.size() == 3);
	REQUIRE(calls[0].first == 'R');
	REQUIRE(samePaths(calls[0].second, {changed}));
	REQUIRE(calls[1].first == 'F');
	REQUIRE(samePaths(calls[1].second, {staticSource}));
	REQUIRE(calls[2].first == 'F');
	REQUIRE(samePaths(calls[2].second, {changed, dependent}));
	REQUIRE(samePaths(plan.filesToIndex, {changed, dependent}));
}

TEST_CASE("refresh contract matches the bounded relational oracle", "[contract][refresh]")
{
	// REFRESH-001: all 64 directed loop-free graphs on three files, all eight choices each
	// of sources, changed files, and unchanged indexed files: 32,768 input snapshots.
	// This checks the real production planner against a separately encoded per-file oracle.
	// It is a bounded executable correspondence check, not a proof for arbitrary file counts.
	const std::array<FilePath, 3> files = {
		FilePath(L"a.cpp"), FilePath(L"b.cpp"), FilePath(L"c.cpp")};
	const std::array<std::pair<size_t, size_t>, 6> possibleEdges = {
		{{0, 1}, {0, 2}, {1, 0}, {1, 2}, {2, 0}, {2, 1}}};
	size_t checked = 0;
	for (unsigned int graph = 0; graph < 64; ++graph)
	{
		bool reaches[3][3] = {};
		Dependencies edges;
		for (size_t edge = 0; edge < possibleEdges.size(); ++edge)
		{
			if (graph & (1u << edge))
			{
				const auto ends = possibleEdges[edge];
				reaches[ends.first][ends.second] = true;
				edges.emplace_back(files[ends.first], files[ends.second]);
			}
		}
		for (size_t via = 0; via < 3; ++via)
		{
			for (size_t from = 0; from < 3; ++from)
			{
				for (size_t to = 0; to < 3; ++to)
				{
					reaches[from][to] = reaches[from][to] || (reaches[from][via] && reaches[via][to]);
				}
			}
		}

		for (unsigned int sourceMask = 0; sourceMask < 8; ++sourceMask)
		{
			for (unsigned int changedMask = 0; changedMask < 8; ++changedMask)
			{
				std::array<bool, 3> affected = {};
				for (size_t file = 0; file < 3; ++file)
				{
					affected[file] = (changedMask & (1u << file)) != 0;
					for (size_t changed = 0; changed < 3; ++changed)
					{
						affected[file] = affected[file] ||
							((changedMask & (1u << changed)) && reaches[file][changed]);
					}
				}
				for (unsigned int unchangedMask = 0; unchangedMask < 8; ++unchangedMask)
				{
					Paths expectedClear;
					Paths expectedIndex;
					for (size_t file = 0; file < 3; ++file)
					{
						bool usedByAffected = false;
						bool usedByStatic = false;
						const bool isSource = (sourceMask & (1u << file)) != 0;
						for (size_t owner = 0; owner < 3; ++owner)
						{
							usedByAffected = usedByAffected ||
								(affected[owner] && reaches[owner][file]);
							usedByStatic = usedByStatic ||
								((sourceMask & (1u << owner)) && !affected[owner] &&
								 reaches[owner][file]);
						}
						const bool cleared = affected[file] ||
							(usedByAffected && !usedByStatic && !isSource);
						if (cleared)
						{
							expectedClear.insert(files[file]);
						}
						if (isSource && (cleared || !(unchangedMask & (1u << file))))
						{
							expectedIndex.insert(files[file]);
						}
					}

					const RefreshPlan actual = planFor(
						pathsForMask(sourceMask, files),
						pathsForMask(unchangedMask, files),
						pathsForMask(changedMask, files),
						edges);
					CAPTURE(graph, sourceMask, changedMask, unchangedMask);
					REQUIRE(samePaths(actual.filesToClear, expectedClear));
					REQUIRE(samePaths(actual.filesToIndex, expectedIndex));
					++checked;
				}
			}
		}
	}
	REQUIRE(checked == 32768);
}
