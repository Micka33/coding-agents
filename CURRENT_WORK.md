let's dig an idea I have

I would like to replace communication via tools like ask_software_architect or ask_product_analyst by allowing the llm to @<deep-agent-name> in a text.

Then a "hook" would identify all @'s in the text and call the mentionned agents.

but I am unclear about how to do that. cause that means a mentionned deepagents would need the whole conversation history in order to answer a mention. I suppose though; they only need the history that is messages from humans and AIs (not tool calls, tasks, etc).
and they will loose their own history when that happens, so when called by the hook; we must merge the history from the caller to the callee by timestamp. that way the callee knows why he is asked that question.
when receiving messages from another deepagent the callee must not mistake these for its own message, he must both - know its own name, and - know the message comes from another participant. same for the caller.

I am thinking to have a centralized conversation history that knows which agent is writing which messages. it doesn't contain any tool call (these are owned by each participants).
This centralized conversation history is agnostic of any owner, every message is from an identified participant. the human can add messages to this conversation but if he doesn't mention a deepagent, none are triggered. when a deepagent is mention, a hook gets the history, merges it with the mentionned agent's history, at the same the hook update the participants name so the agent believes he is then owner of the conversation, so all his previous messages aren't by a named participants; they from himself (I think participants are identified by the key "role" in langchain, that must be confirmed).
when a deepagent replies, its messages (only the final one, not tools calls, etc) is extracted, updated to its name and synchronized into the centralized conversation history.

any update to the centralized conversation history must trigger the hook (ex: an agent can mention another agent directly too).

since new message can be added to the centralized history while an agent is busy replying, and these message can also mention that agent, the hook must queue a trigger, however it can only queue a single trigger a new mention must not queue a new trigger.
In the example below agentB is already busy thinking and replying to the user's first mention but was mentioned twice more, so a trigger has been queued, and when agentB is done a new conversation sync (centralised to agentB) will be triggered:
user: @agentA .....
agentA: ..... but better ask @agentB
@agentB: .........
user: @agentB xxx...
user: @agentB yyy...
user: @agentB zzz...
<agentB is thinking about xxx...>
<waiting for agentB's to be done before triggering again>

deepagents must know their own name, so if >10k tokens have been added to the conversation hisotry since previous reply, a system message must be added to the history such as <you are agentB, other participants in this conversation will refer to you as "@agentB">.
