# this module defines the agent's write actions, so the design goal is converting silent corruption into loud, recoverable failure, 
# patches are anchor based because LLMs cannot count character offsets, a wrong offset corrupts a file silently, 
# a wrong anchor fails with a structured error the agent can retry
# compilation is sandboxed: no shell escape, timeout, size cap, temp dirs

