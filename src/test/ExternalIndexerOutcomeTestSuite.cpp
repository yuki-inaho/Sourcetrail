#include "catch.hpp"

#include <thread>
#include <vector>

#include "Blackboard.h"
#include "DialogView.h"
#include "ExternalIndexerRunState.h"
#include "MessageIndexingFinished.h"
#include "MessageQuitApplication.h"
#include "TaskFinishParsing.h"

TEST_CASE("external execution result is preserved by terminal messages", "[contract][execution]")
{
	// Existing message callers retain their successful default.
	REQUIRE(MessageIndexingFinished().exitCode == 0);
	REQUIRE(MessageQuitApplication().exitCode == 0);
	const MessageIndexingFinished finished(1);
	const MessageQuitApplication quit(finished.exitCode);
	REQUIRE(finished.exitCode == 1);
	REQUIRE(quit.exitCode == 1);
}

TEST_CASE("external run counts concurrent attempts and retains every failure", "[contract][execution]")
{
	using sourcetrail::core::ExternalProcessOutcome;
	ExternalIndexerRunState state;
	std::vector<std::thread> workers;
	for (int worker = 0; worker < 8; ++worker)
	{
		workers.emplace_back([&state]() {
			for (int command = 0; command < 60; ++command)
			{
				state.beginCommand();
				const ExternalProcessOutcome outcome = command % 3 == 0 ?
					ExternalProcessOutcome::Succeeded : (command % 3 == 1 ?
						ExternalProcessOutcome::TransportError : ExternalProcessOutcome::NonzeroExit);
				state.settleCommand(outcome);
			}
		});
	}
	for (std::thread& worker: workers)
	{
		worker.join();
	}
	const auto result = state.snapshot();
	REQUIRE(result.attempted == 480);
	REQUIRE(result.settled == 480);
	REQUIRE(result.succeeded == 160);
	REQUIRE(result.failed == 320);
	REQUIRE(result.hasFailure());
	REQUIRE(result.exitCode() == 1);
}

namespace
{
class TrackingFinishDialog: public DialogView
{
public:
	TrackingFinishDialog(): DialogView(UseCase::INDEXING, nullptr) {}

	void clearDialogs() override
	{
		++clearCalls;
	}

	void hideUnknownProgressDialog() override
	{
		++unknownProgressHideCalls;
	}

	DatabasePolicy finishedIndexingDialog(
		size_t, size_t, size_t, size_t, float, ErrorCountInfo, bool, bool) override
	{
		++finishedCalls;
		return DATABASE_POLICY_KEEP;
	}

	int finishedCalls = 0;
	int clearCalls = 0;
	int unknownProgressHideCalls = 0;
};
}

TEST_CASE("failed external run finishes scheduling and forces candidate discard", "[contract][execution]")
{
	// A null storage proves the failure path neither queries nor optimizes the
	// candidate. A KEEP-returning dialog must never be offered failed output.
	auto state = std::make_shared<ExternalIndexerRunState>();
	state->beginCommand();
	state->settleCommand(sourcetrail::core::ExternalProcessOutcome::NonzeroExit);
	auto dialog = std::make_shared<TrackingFinishDialog>();
	auto blackboard = std::make_shared<Blackboard>();
	blackboard->set("indexed_source_file_count", 0);
	blackboard->set("source_file_count", 1);
	TaskFinishParsing finish(nullptr, dialog, state);
	REQUIRE(finish.update(blackboard) == Task::STATE_SUCCESS);
	bool discard = false;
	REQUIRE(blackboard->get("discard_database", discard));
	REQUIRE(discard);
	REQUIRE_FALSE(blackboard->exists("keep_database"));
	REQUIRE(dialog->finishedCalls == 0);
	REQUIRE(dialog->clearCalls == 1);
	REQUIRE(dialog->unknownProgressHideCalls == 0);
}

TEST_CASE("invalid output rejects a run without inventing a process failure", "[contract][execution]")
{
	ExternalIndexerRunState state;
	state.beginCommand();
	state.settleCommand(sourcetrail::core::ExternalProcessOutcome::Succeeded);
	state.rejectOutput();
	state.beginCommand();
	state.settleCommand(sourcetrail::core::ExternalProcessOutcome::Succeeded);
	const auto result = state.snapshot();
	REQUIRE(result.attempted == 2);
	REQUIRE(result.settled == 2);
	REQUIRE(result.succeeded == 2);
	REQUIRE(result.failed == 0);
	REQUIRE(result.invalidOutputs == 1);
	REQUIRE(result.hasFailure());
	REQUIRE(result.exitCode() == 1);
}
