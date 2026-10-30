#include "RefreshPlan.h"

RefreshPlan RefreshPlan::forUpdatedFiles(
	const FilePaths& allSourceFiles,
	const FilePaths& unchangedIndexedFiles,
	const FilePaths& changedFiles,
	const DependencyQuery& referenced,
	const DependencyQuery& referencing)
{
	RefreshPlan plan;
	plan.filesToClear = changedFiles;
	const FilePaths dependentFiles = referencing(changedFiles);
	plan.filesToClear.insert(dependentFiles.begin(), dependentFiles.end());

	FilePaths staticSourceFiles = allSourceFiles;
	for (const FilePath& path: plan.filesToClear)
	{
		staticSourceFiles.erase(path);
	}

	const FilePaths staticReferencedFiles = referenced(staticSourceFiles);
	const FilePaths dynamicReferencedFiles = referenced(plan.filesToClear);
	for (const FilePath& path: dynamicReferencedFiles)
	{
		if (staticReferencedFiles.find(path) == staticReferencedFiles.end() &&
			staticSourceFiles.find(path) == staticSourceFiles.end())
		{
			plan.filesToClear.insert(path);
		}
	}

	for (const FilePath& path: allSourceFiles)
	{
		if (plan.filesToClear.find(path) != plan.filesToClear.end() ||
			unchangedIndexedFiles.find(path) == unchangedIndexedFiles.end())
		{
			plan.filesToIndex.insert(path);
		}
	}
	return plan;
}
