#include "RefreshPlanner.h"

#include <array>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

namespace
{
using Files = std::set<unsigned int>;
using Matrix = std::array<std::array<bool, 3>, 3>;

void require(bool condition, const std::string& message)
{
	// Unlike assert(), the contract must also run in Release/NDEBUG builds.
	if (!condition)
	{
		throw std::runtime_error(message);
	}
}

Files filesForMask(unsigned int mask)
{
	Files files;
	for (unsigned int file = 0; file < 3; ++file)
	{
		if (mask & (1u << file))
		{
			files.insert(file);
		}
	}
	return files;
}

Files reachable(const Matrix& reaches, const Files& seeds, bool reverse)
{
	Files result;
	for (unsigned int from: seeds)
	{
		for (unsigned int to = 0; to < 3; ++to)
		{
			if (reverse ? reaches[to][from] : reaches[from][to])
			{
				result.insert(to);
			}
		}
	}
	return result;
}

void verifyNamedExamples()
{
	const Files sources {0, 1};
	const Files changed {0};
	const auto selection = sourcetrail::core::prepareUpdatedRefresh(sources, changed, Files {});
	require(selection.initialFilesToClear == Files {0}, "changed source must be affected");
	require(selection.staticSourceFiles == Files {1}, "unchanged source must be retained");
	const auto shared = sourcetrail::core::finishUpdatedRefresh(
		sources, Files {1}, selection, Files {2}, Files {2, 3});
	require(shared.filesToClear == Files({0, 3}), "keep shared dependency 2, clear private 3");
	require(shared.filesToIndex == Files {0}, "only affected source must be indexed");
	require(sources == Files({0, 1}) && changed == Files {0}, "input values must be unchanged");

	const auto addedRemoved = sourcetrail::core::prepareUpdatedRefresh(
		Files {0, 1}, Files {2}, Files {});
	const auto updated = sourcetrail::core::finishUpdatedRefresh(
		Files {0, 1}, Files {0}, addedRemoved, Files {}, Files {});
	require(updated.filesToClear == Files {2}, "removed source must be cleared");
	require(updated.filesToIndex == Files {1}, "new source must be indexed");

	const auto emptySelection = sourcetrail::core::prepareUpdatedRefresh(Files {}, Files {}, Files {});
	const auto empty = sourcetrail::core::finishUpdatedRefresh(
		Files {}, Files {}, emptySelection, Files {}, Files {});
	require(empty.filesToClear.empty() && empty.filesToIndex.empty(), "empty input is a no-op");
}

// An adapter may have ordered identity without equality (FilePath's equality even performs
// filesystem checks). This type makes an accidental equality requirement a compile error.
struct OrderedIdentity
{
	int value;
	bool operator<(const OrderedIdentity& other) const { return value < other.value; }
	bool operator==(const OrderedIdentity&) const = delete;
};

void verifyOpaqueIdentity()
{
	using Identities = std::set<OrderedIdentity>;
	const Identities sources {{2}, {7}};
	const auto selection = sourcetrail::core::prepareUpdatedRefresh(
		sources, Identities {{7}}, Identities {});
	const auto plan = sourcetrail::core::finishUpdatedRefresh(
		sources, Identities {{2}}, selection, Identities {}, Identities {});
	require(plan.filesToClear.size() == 1 && plan.filesToClear.begin()->value == 7,
		"opaque identities must preserve ordered-set membership");
	require(plan.filesToIndex.size() == 1 && plan.filesToIndex.begin()->value == 7,
		"opaque identities must not require equality or path conversion");
}

unsigned int verifyBoundedOracle()
{
	// The oracle computes Boolean reachability and a per-file truth predicate, independently
	// of the core's two-stage set operations. Enumerate every loop-free directed graph on
	// three identities and every source/changed/unchanged subset, including overlapping input.
	const std::array<std::pair<unsigned int, unsigned int>, 6> edges = {
		{{0, 1}, {0, 2}, {1, 0}, {1, 2}, {2, 0}, {2, 1}}};
	unsigned int checked = 0;
	for (unsigned int graph = 0; graph < 64; ++graph)
	{
		Matrix reaches {};
		for (unsigned int edge = 0; edge < edges.size(); ++edge)
		{
			if (graph & (1u << edge))
			{
				reaches[edges[edge].first][edges[edge].second] = true;
			}
		}
		for (unsigned int via = 0; via < 3; ++via)
		{
			for (unsigned int from = 0; from < 3; ++from)
			{
				for (unsigned int to = 0; to < 3; ++to)
				{
					reaches[from][to] = reaches[from][to] || (reaches[from][via] && reaches[via][to]);
				}
			}
		}
		for (unsigned int sourceMask = 0; sourceMask < 8; ++sourceMask)
		{
			for (unsigned int changedMask = 0; changedMask < 8; ++changedMask)
			{
				std::array<bool, 3> affected {};
				for (unsigned int file = 0; file < 3; ++file)
				{
					affected[file] = (changedMask & (1u << file)) != 0;
					for (unsigned int changed = 0; changed < 3; ++changed)
					{
						affected[file] = affected[file] ||
							((changedMask & (1u << changed)) && reaches[file][changed]);
					}
				}
				for (unsigned int unchangedMask = 0; unchangedMask < 8; ++unchangedMask)
				{
					Files expectedClear;
					Files expectedIndex;
					for (unsigned int file = 0; file < 3; ++file)
					{
						bool usedByAffected = false;
						bool usedByStatic = false;
						const bool isSource = (sourceMask & (1u << file)) != 0;
						for (unsigned int owner = 0; owner < 3; ++owner)
						{
							usedByAffected = usedByAffected || (affected[owner] && reaches[owner][file]);
							usedByStatic = usedByStatic ||
								((sourceMask & (1u << owner)) && !affected[owner] && reaches[owner][file]);
						}
						const bool cleared = affected[file] ||
							(usedByAffected && !usedByStatic && !isSource);
						if (cleared)
						{
							expectedClear.insert(file);
						}
						if (isSource && (cleared || !(unchangedMask & (1u << file))))
						{
							expectedIndex.insert(file);
						}
					}
					const Files sources = filesForMask(sourceMask);
					const Files changed = filesForMask(changedMask);
					const auto selection = sourcetrail::core::prepareUpdatedRefresh(
						sources, changed, reachable(reaches, changed, true));
					const auto plan = sourcetrail::core::finishUpdatedRefresh(
						sources,
						filesForMask(unchangedMask),
						selection,
						reachable(reaches, selection.staticSourceFiles, false),
						reachable(reaches, selection.initialFilesToClear, false));
					const std::string input = "graph=" + std::to_string(graph) +
						", sources=" + std::to_string(sourceMask) +
						", changed=" + std::to_string(changedMask) +
						", unchanged=" + std::to_string(unchangedMask);
					require(plan.filesToClear == expectedClear, "clear mismatch: " + input);
					require(plan.filesToIndex == expectedIndex, "index mismatch: " + input);
					++checked;
				}
			}
		}
	}
	return checked;
}
} // namespace

int main()
{
	try
	{
		verifyNamedExamples();
		verifyOpaqueIdentity();
		const unsigned int checked = verifyBoundedOracle();
		require(checked == 32768, "bounded oracle did not cover the promised input count");
		std::cout << "Refresh core: named examples, opaque identity, and " << checked
			<< " bounded input snapshots passed.\n";
		return 0;
	}
	catch (const std::exception& error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
