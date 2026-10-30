#ifndef SOURCETRAIL_CORE_REFRESH_PLANNER_H
#define SOURCETRAIL_CORE_REFRESH_PLANNER_H

#include <set>

namespace sourcetrail
{
namespace core
{

// Identity is the ordered-set key supplied by the adapter. The core never opens a file,
// canonicalizes a path, consults storage, or uses Key::operator==. Integer IDs are sufficient
// for another host or language to implement the same finite-set contract.
template <typename Key>
struct RefreshSelection
{
	std::set<Key> initialFilesToClear;
	std::set<Key> staticSourceFiles;
};

template <typename Key>
struct RefreshPlan
{
	std::set<Key> filesToClear;
	std::set<Key> filesToIndex;
};

// REFRESH-001: The adapter supplies referencing(changedFiles) from one fixed snapshot.
// Returning the two query seed sets separates selection from dependency retrieval.
template <typename Key>
RefreshSelection<Key> prepareUpdatedRefresh(
	const std::set<Key>& allSourceFiles,
	const std::set<Key>& changedFiles,
	const std::set<Key>& referencingChangedFiles)
{
	RefreshSelection<Key> selection;
	selection.initialFilesToClear = changedFiles;
	selection.initialFilesToClear.insert(
		referencingChangedFiles.begin(), referencingChangedFiles.end());
	selection.staticSourceFiles = allSourceFiles;
	for (const Key& file: selection.initialFilesToClear)
	{
		selection.staticSourceFiles.erase(file);
	}
	return selection;
}

// Supply the same allSourceFiles used by prepareUpdatedRefresh and the results of
// referenced(selection.staticSourceFiles), then referenced(selection.initialFilesToClear).
// All dependency results must describe the same snapshot. Computing relation closure,
// including whether include/import relations are separate, belongs to the adapter.
template <typename Key>
RefreshPlan<Key> finishUpdatedRefresh(
	const std::set<Key>& allSourceFiles,
	const std::set<Key>& unchangedIndexedFiles,
	const RefreshSelection<Key>& selection,
	const std::set<Key>& staticReferencedFiles,
	const std::set<Key>& dynamicReferencedFiles)
{
	RefreshPlan<Key> plan;
	plan.filesToClear = selection.initialFilesToClear;
	// REFRESH-002: Shared dependencies and unaffected source files survive cleanup.
	for (const Key& file: dynamicReferencedFiles)
	{
		if (staticReferencedFiles.find(file) == staticReferencedFiles.end() &&
			selection.staticSourceFiles.find(file) == selection.staticSourceFiles.end())
		{
			plan.filesToClear.insert(file);
		}
	}
	for (const Key& file: allSourceFiles)
	{
		if (plan.filesToClear.find(file) != plan.filesToClear.end() ||
			unchangedIndexedFiles.find(file) == unchangedIndexedFiles.end())
		{
			plan.filesToIndex.insert(file);
		}
	}
	return plan;
}

} // namespace core
} // namespace sourcetrail

#endif // SOURCETRAIL_CORE_REFRESH_PLANNER_H
