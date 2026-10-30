#ifndef SOURCETRAIL_CORE_EXTERNAL_INDEXER_OUTCOME_H
#define SOURCETRAIL_CORE_EXTERNAL_INDEXER_OUTCOME_H

#include <cstddef>
#include <stdexcept>

namespace sourcetrail
{
namespace core
{

enum class ExternalProcessOutcome
{
	Succeeded,
	TransportError,
	NonzeroExit
};

// EXECUTION-001: output, parser diagnostics and graph completeness are separate
// observations. A transport error wins even when an exit-code field contains zero.
inline ExternalProcessOutcome classifyExternalProcess(bool hasTransportError, int exitCode)
{
	if (hasTransportError)
	{
		return ExternalProcessOutcome::TransportError;
	}
	return exitCode == 0 ? ExternalProcessOutcome::Succeeded : ExternalProcessOutcome::NonzeroExit;
}

struct ExternalIndexerOutcome
{
	std::size_t attempted = 0;
	std::size_t settled = 0;
	std::size_t succeeded = 0;
	std::size_t failed = 0;

	void beginCommand()
	{
		++attempted;
	}

	// Each command must be settled exactly once after beginCommand. The execution
	// adapter owns command identities and joins workers before finalization.
	void settleCommand(ExternalProcessOutcome outcome)
	{
		if (settled >= attempted)
		{
			throw std::logic_error("Cannot settle an external command that was not started");
		}
		switch (outcome)
		{
		case ExternalProcessOutcome::Succeeded:
			++succeeded;
			break;
		case ExternalProcessOutcome::TransportError:
		case ExternalProcessOutcome::NonzeroExit:
			++failed;
			break;
		default:
			throw std::invalid_argument("Unknown external process outcome");
		}
		++settled;
	}

	bool hasFailure() const
	{
		return failed != 0;
	}

	// Call after the adapter's worker barrier. Zero describes process execution,
	// not output validity, cancellation, timeout behavior or a complete index.
	int exitCode() const
	{
		return hasFailure() ? 1 : 0;
	}
};

} // namespace core
} // namespace sourcetrail

#endif // SOURCETRAIL_CORE_EXTERNAL_INDEXER_OUTCOME_H
