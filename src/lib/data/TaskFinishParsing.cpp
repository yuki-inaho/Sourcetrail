#include "TaskFinishParsing.h"

#include <utility>

#include "Blackboard.h"
#include "DialogView.h"
#include "ExternalIndexerRunState.h"
#include "MessageIndexingFinished.h"
#include "MessageIndexingStatus.h"
#include "MessageStatus.h"
#include "PersistentStorage.h"
#include "TimeStamp.h"
#include "utilityString.h"

TaskFinishParsing::TaskFinishParsing(
	std::shared_ptr<PersistentStorage> storage,
	std::shared_ptr<DialogView> dialogView,
	std::shared_ptr<ExternalIndexerRunState> runState)
	: m_storage(storage)
	, m_dialogView(dialogView)
	, m_runState(runState ? std::move(runState) : std::make_shared<ExternalIndexerRunState>())
{
}

void TaskFinishParsing::terminate()
{
	m_dialogView->clearDialogs();

	MessageStatus(L"An unknown exception was thrown during indexing.", true, false).dispatch();
	MessageIndexingFinished().dispatch();
}

void TaskFinishParsing::doEnter(std::shared_ptr<Blackboard> blackboard)
{
	if (!m_runState->snapshot().hasFailure())
	{
		m_storage->setMode(SqliteIndexStorage::STORAGE_MODE_READ);
	}
}

Task::TaskState TaskFinishParsing::doUpdate(std::shared_ptr<Blackboard> blackboard)
{
	const sourcetrail::core::ExternalIndexerOutcome outcome = m_runState->snapshot();
	if (outcome.hasFailure())
	{
		// EXECUTION-001: execution failure is independent of parser diagnostics.
		// Complete the task sequence so it closes and discards the candidate before
		// sending the terminal result. Never offer failed process output for adoption.
		int indexedSourceFileCount = 0;
		blackboard->get("indexed_source_file_count", indexedSourceFileCount);
		int sourceFileCount = 0;
		blackboard->get("source_file_count", sourceFileCount);
		MessageStatus(
			L"Indexing failed: " + std::to_wstring(indexedSourceFileCount) + L"/" +
				std::to_wstring(sourceFileCount) + L" source files indexed; " +
				std::to_wstring(outcome.failed) +
				L" external commands failed. Discarding temporary index.",
			true,
			false)
			.dispatch();
		// Custom execution uses an indexing-progress dialog, not an unknown-progress
		// dialog. Clear the active terminal UI and unblock the project in either case.
		m_dialogView->clearDialogs();
		MessageIndexingStatus(false).dispatch();
		blackboard->set("discard_database", true);
		return STATE_SUCCESS;
	}

	TimeStamp start = TimeStamp::now();

	m_dialogView->showUnknownProgressDialog(L"Finish Indexing", L"Optimizing database");
	m_storage->optimizeMemory();
	m_dialogView->hideUnknownProgressDialog();

	double time = TimeStamp::durationSeconds(start);

	if (blackboard->exists("clear_time"))
	{
		float clearTime = 0;
		blackboard->get("clear_time", clearTime);
		time += clearTime;
	}

	if (blackboard->exists("index_time"))
	{
		float indexTime = 0;
		blackboard->get("index_time", indexTime);
		time += indexTime;
	}

	int indexedSourceFileCount = 0;
	blackboard->get("indexed_source_file_count", indexedSourceFileCount);

	int sourceFileCount = 0;
	blackboard->get("source_file_count", sourceFileCount);

	bool interruptedIndexing = false;
	blackboard->get("interrupted_indexing", interruptedIndexing);

	bool shallowIndexing = false;
	blackboard->get("shallow_indexing", shallowIndexing);

	ErrorCountInfo errorInfo = m_storage->getErrorCount();

	std::wstring status;
	status += L"Finished indexing: ";
	status += std::to_wstring(indexedSourceFileCount) + L"/" + std::to_wstring(sourceFileCount) +
		L" source files indexed; ";
	status += utility::decodeFromUtf8(TimeStamp::secondsToString(time));
	status += L"; " + std::to_wstring(errorInfo.total) + L" error" +
		(errorInfo.total != 1 ? L"s" : L"");
	if (errorInfo.fatal > 0)
	{
		status += L" (" + std::to_wstring(errorInfo.fatal) + L" fatal)";
	}
	MessageStatus(status, false, false).dispatch();

	StorageStats stats = m_storage->getStorageStats();
	DatabasePolicy policy = m_dialogView->finishedIndexingDialog(
		indexedSourceFileCount,
		sourceFileCount,
		stats.completedFileCount,
		stats.fileCount,
		static_cast<float>(time),
		errorInfo,
		interruptedIndexing,
		shallowIndexing);

	MessageIndexingStatus(false).dispatch();

	if (policy == DATABASE_POLICY_KEEP)
	{
		blackboard->set("keep_database", true);
	}
	else if (policy == DATABASE_POLICY_DISCARD)
	{
		blackboard->set("discard_database", true);
	}
	else if (policy == DATABASE_POLICY_REFRESH)
	{
		blackboard->set("keep_database", true);
		blackboard->set("refresh_database", true);
	}

	return STATE_SUCCESS;
}

void TaskFinishParsing::doExit(std::shared_ptr<Blackboard> blackboard)
{
	m_storage.reset();
}

void TaskFinishParsing::doReset(std::shared_ptr<Blackboard> blackboard) {}
