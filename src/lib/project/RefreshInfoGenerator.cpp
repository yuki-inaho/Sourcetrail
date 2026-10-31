#include "RefreshInfoGenerator.h"

#include "FileInfo.h"
#include "FileSystem.h"
#include "PersistentStorage.h"
#include "RefreshInfo.h"
#include "RefreshPlan.h"
#include "SourceChange.h"
#include "SourceGroup.h"
#include "SourceGroupStatusType.h"
#include "TextAccess.h"
#include "utility.h"

RefreshInfo RefreshInfoGenerator::getRefreshInfoForUpdatedFiles(
	const std::vector<std::shared_ptr<SourceGroup>>& sourceGroups,
	std::shared_ptr<const PersistentStorage> storage)
{
	// 1) Divide filepaths that are already known by the storage to "unchanged and indexed",
	// "unchanged and non-indexed" and "changed"
	std::set<FilePath> unchangedIndexedFilePaths;
	std::set<FilePath> unchangedNonindexedFilePaths;
	std::set<FilePath> changedFilePaths;

	{
		const std::vector<FileInfo> fileInfosFromStorage = storage->getFileInfoForAllFiles();

		std::set<FilePath> alreadyKnownPaths;
		{
			const std::set<FilePath> filePathsFromStorage = utility::toSet(
				utility::convert<FileInfo, FilePath>(
					fileInfosFromStorage, [](const FileInfo& info) { return info.path; }));

			for (std::shared_ptr<SourceGroup> sourceGroup: sourceGroups)
			{
				if (sourceGroup->getStatus() == SOURCE_GROUP_STATUS_ENABLED)
				{
					utility::append(
						alreadyKnownPaths,
						sourceGroup->filterToContainedFilePaths(filePathsFromStorage));
				}
			}
		}

		// checking source and header files
		for (const FileInfo& info: fileInfosFromStorage)
		{
			if (alreadyKnownPaths.find(info.path) != alreadyKnownPaths.end() && info.path.exists())
			{
				if (storage->getFilePathIndexed(info.path))
				{
					if (didFileChange(info, storage))
					{
						changedFilePaths.insert(info.path);
					}
					else
					{
						unchangedIndexedFilePaths.insert(info.path);
					}
				}
				else
				{
					changedFilePaths.insert(info.path);
				}
			}
			else if (!storage->getFilePathIndexed(info.path) && !didFileChange(info, storage))
			{
				unchangedNonindexedFilePaths.insert(info.path);
			}
			else	// file has been removed
			{
				changedFilePaths.insert(info.path);
			}
		}
	}

	const RefreshPlan plan = RefreshPlan::forUpdatedFiles(
		getAllSourceFilePaths(sourceGroups),
		unchangedIndexedFilePaths,
		changedFilePaths,
		[&storage](const RefreshPlan::FilePaths& paths) { return storage->getReferenced(paths); },
		[&storage](const RefreshPlan::FilePaths& paths) { return storage->getReferencing(paths); });

	// The IO adapter retains the storage-specific indexed/non-indexed partition.
	RefreshInfo info;
	info.mode = REFRESH_UPDATED_FILES;
	info.filesToIndex = plan.filesToIndex;
	for (const FilePath& fileToClear: plan.filesToClear)
	{
		if (storage->getFilePathIndexed(fileToClear))
		{
			info.filesToClear.insert(fileToClear);
		}
		else
		{
			info.nonIndexedFilesToClear.insert(fileToClear);
		}
	}

	return info;
}

RefreshInfo RefreshInfoGenerator::getRefreshInfoForIncompleteFiles(
	const std::vector<std::shared_ptr<SourceGroup>>& sourceGroups,
	std::shared_ptr<const PersistentStorage> storage)
{
	RefreshInfo info = getRefreshInfoForUpdatedFiles(sourceGroups, storage);
	info.mode = REFRESH_UPDATED_AND_INCOMPLETE_FILES;

	std::set<FilePath> incompleteFiles;
	{
		const std::set<FilePath> filesToClear = utility::concat(
			info.filesToClear, info.nonIndexedFilesToClear);
		for (const FilePath& path: storage->getIncompleteFiles())
		{
			if (filesToClear.find(path) == filesToClear.end())
			{
				incompleteFiles.insert(path);
			}
		}
	}

	if (!incompleteFiles.empty())
	{
		utility::append(incompleteFiles, storage->getReferencing(incompleteFiles));

		std::set<FilePath> staticSourceFilePaths = getAllSourceFilePaths(sourceGroups);
		for (const FilePath& path: incompleteFiles)
		{
			staticSourceFilePaths.erase(path);

			if (storage->getFilePathIndexed(path))
			{
				info.filesToClear.insert(path);
			}
			else
			{
				info.nonIndexedFilesToClear.insert(path);
			}
		}

		for (const std::shared_ptr<const SourceGroup>& sourceGroup: sourceGroups)
		{
			if (sourceGroup->getStatus() == SOURCE_GROUP_STATUS_ENABLED)
			{
				utility::append(
					info.filesToIndex, sourceGroup->getSourceFilePathsExcept(staticSourceFilePaths));
			}
		}
	}

	return info;
}

RefreshInfo RefreshInfoGenerator::getRefreshInfoForAllFiles(
	const std::vector<std::shared_ptr<SourceGroup>>& sourceGroups)
{
	RefreshInfo info;
	info.mode = REFRESH_ALL_FILES;
	info.filesToIndex = getAllSourceFilePaths(sourceGroups);
	return info;
}

std::set<FilePath> RefreshInfoGenerator::getAllSourceFilePaths(
	const std::vector<std::shared_ptr<SourceGroup>>& sourceGroups)
{
	std::set<FilePath> allSourceFilePaths;

	for (const std::shared_ptr<const SourceGroup>& sourceGroup: sourceGroups)
	{
		if (sourceGroup->getStatus() == SOURCE_GROUP_STATUS_ENABLED)
		{
			for (const FilePath& sourceFilePath: sourceGroup->getAllSourceFilePaths())
			{
				if (sourceFilePath.exists())
				{
					allSourceFilePaths.insert(sourceFilePath);
				}
			}
		}
	}

	return allSourceFilePaths;
}

bool RefreshInfoGenerator::didFileChange(
	const FileInfo& info, std::shared_ptr<const PersistentStorage> storage)
{
	using namespace sourcetrail::core;
	FileInfo diskFileInfo = FileSystem::getFileInfoForPath(info.path);
	const std::shared_ptr<TextAccess> diskContent = TextAccess::tryCreateFromFile(info.path);
	const SourceContent current {diskContent ? SourceContentStatus::Available :
		SourceContentStatus::ReadError, diskContent ? diskContent->getText() : std::string()};
	return didSourceChange(storage->getFilePathIndexed(info.path),
		storage->tryGetStoredFileContent(info.path), current,
		diskFileInfo.lastWriteTime > info.lastWriteTime);
}
