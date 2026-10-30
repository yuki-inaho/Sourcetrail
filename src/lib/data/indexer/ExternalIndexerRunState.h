#ifndef EXTERNAL_INDEXER_RUN_STATE_H
#define EXTERNAL_INDEXER_RUN_STATE_H

#include <mutex>

#include "ExternalIndexerOutcome.h"

// One instance belongs to one indexing run. Scheduling and storage stay outside
// the portable outcome policy; the adapter serializes updates from its workers.
class ExternalIndexerRunState
{
public:
	sourcetrail::core::ExternalIndexerOutcome beginCommand()
	{
		std::lock_guard<std::mutex> lock(m_mutex);
		m_outcome.beginCommand();
		return m_outcome;
	}

	void settleCommand(sourcetrail::core::ExternalProcessOutcome outcome)
	{
		std::lock_guard<std::mutex> lock(m_mutex);
		m_outcome.settleCommand(outcome);
	}

	sourcetrail::core::ExternalIndexerOutcome snapshot() const
	{
		std::lock_guard<std::mutex> lock(m_mutex);
		return m_outcome;
	}

private:
	mutable std::mutex m_mutex;
	sourcetrail::core::ExternalIndexerOutcome m_outcome;
};

#endif // EXTERNAL_INDEXER_RUN_STATE_H
