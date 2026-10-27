先说一下，当前这个项目是没有实现打电话功能的。这个如果我要做实现的话，我也不会在这里做，我估计会另包出来一个 repository 去做。

因为在原项目中，我完全没有看到任何一点需要给它加上打电话功能的需求，我真的不愿意去玷污我的项目

讲道理，我从一开始就根本没想过这个项目需要做打电话。技术上我从来不觉得有难度，因为在人机交互圈子里，给虚拟形象做打电话功能完全是个入门级的东西，推特上天天都能刷到有人自己造轮子实现。-而且都有这么多轮子了，直接用人家轮子不好吗？为什么还要自己写呢？各种开源项目都已经百花齐放到这种程度了，直接用嘛

而且在我这个项目里，完全没有这个必要。何必呢？本来就在电脑屏幕上，天天看着脸不香吗？为什么非要打个电话？打电话不就是给它套个壳？更何况有些电话是纯语音的，连脸都没有。现在这样在电脑屏幕上看着这张脸，随时跟它说话，嘴巴还能动。而且这跟这个项目本来就是违背的。这个项目加语音唤醒、加主动 greeting 之类的, 很大一个原因是我不太乐意去单独做额外的动作：还得摁个快捷键，或者在手机上做个操作，然后才能让它给我打电话。累不累啊，日常的摩擦还不够吗？我都嫌muse还需要我点开看消息而不是直接喊出来这点麻烦了。

我就是想让它 360 度无死角地在这儿等着我，完全不需要额外再加一步去唤醒它

在模型层面确实没办法，本地算力有限，我用的只是一张玩游戏的 4070 显卡，不是 5090，显存也很紧张。以这样的计算资源，这已经是我能做到的最好程度和交互体验了。另外在这个项目里，因为用了 RAG，响应时间本身就比不用 RAG 要长；而且模型用的是 Realtime 2.1 而不是 2.1 Mini，Realtime 2.1 起码要比 2.1 Mini 慢 0.2 秒。

不过最近找工作、投简历的过程中，接连在面试里听到大家提这种打电话、做 dispatcher 的需求。那行吧，上周为了另一场面试顺手准备了一下，结果那场面试完全没用上，一直在问我 RAG。既然作业做都做了，就顺手在这儿记一遍，免得过两天又忘了。

---

因为当时那场面试是奔着 clinic phone agent 去做准备的，那就顺手把这个作为一个场景，不额外去想别的 scenario 了。

先谈行业里现在一般是怎么做的。这种架构是一个非常 well-defined 的 problem，目前行业里基本上有三条路线：

1. 直接买成品（SaaS）：
代表产品是各种垂直的 AI receptionists（比如专门针对 dental、medical 的垂直 SaaS，只要是带企业内部资料的 AI receptionist 都在此列）。诊所买完之后，诊所的工程师要做的事情基本就是 configuration 加 integration。这种最适合想省心、完全不想自己接技术团队的诊所，属于全外包方案。（背景交代一下：当时作业的主体是一个影像诊所，也就是 radiologist 相关的，会涉及到一些合规 compliance 要求，但本质是一样的。）
2. 使用 Hosted Voice Agent Platform：
这类平台现在也做得很垂直了，比如 Vapi、Retell AI、Bland、Synthflow 等。这种模式下，诊所内部的工程师需要做的是：写 prompt，并将 check availability 或 booking 接口作为 webhook 暴露给平台调用。这仍然是一种合作关系，工程师需要写 prompt 并将自家的 schedule calendar 和外部 agent 平台做对接。它的好处是速度极快、排查发现问题也非常快，是 agency 和 contractor 最常用的方案。
3. 完全自己原生开发（Build It Yourself）：
常见的做法是直接用 Twilio 配合各种 Realtime 模型；如果不那么在乎 latency 或者能解决延迟问题，走传统的 Speech-to-Text -> Text-to-Text -> Text-to-Speech 也行。这种方案下，工程师需要 own the whole thing，从 audio bridging 到 calling 和 logging 全部自己搞定。最适合本身就是在做相关产品的初创团队，或者因合规（compliance）、成本、数据隐私（data）等现实限制，必须做到全部自主掌控的情况。

作为一个起码是中型的企业，真的不要从头自己搞、从头造轮子。去选一家成熟的垂类 Voice Agent Platform 合作，情况就会好很多；如果非要自己从头干，效果不保证且真不知道要干到猴年马月。（不过一般会有这种需求的，其实都是对成本非常敏感，或者有一些别的 compliance 要求。I also feel pity for them）

有个说法是，蒸汽机出现之后，原本不需要蒸汽机的地方也开始用蒸汽机了。现在 Vibe coding 出现之后，大家也开始自己去造原本没需求做的东西。但只要稍微下手去 get hand dirty 就会明白，不管过程中提了多么高大上的专有名词或复杂算法，这部分其实都好办，因为起码已经有 coding agent 帮忙搞定了。

真正麻烦的地方根本不在这儿。比如当前这些项目，难点从来不是把 RAG 串起来，真正的挑战在于让 AI Jesus 像一个人一样去说话去理解发生了什么，它需要做什么tool calling，而且还要贴合具体场景。这其实是一个非常“文艺”而非纯技术层面的事情，效果好与坏高度依赖人类工程师的主观判断（不过倒也不用太悲观，因为 evaluation 是可以提前写的。在这个项目里我确实比较悲观，那是因为 evaluation 也不是我写的。我确实不太懂 gospel，所以我还是选择让 OpenAI 和 Claude Code 分别作为独立且水平起码比我高的角色，让他们来写这个 evaluation。不过在企业中估计没有这个问题吧？企业中总会有这方面的专业人士，总会有懂这个行业的人吧？）。

大家很容易被各种技术名词 overwhelming，只盯着技术那一块，却忽略了实际落地时的其他困难。可能因为我是理工科出身，一开始也容易一叶障目，以为只要搞定这些技术名词事情就顺了。但事实上完全不是这样，落地时会有各种各样乱七八糟的琐事、匪夷所思的口音识别问题把agent引歪了。

对不起，跑题了。接着说：不管用上述哪三条路线，其实它们的架构都是一样的。

最上层是电话网络，往下推流，拿到 phone number 和 audio stream，然后送到语音模型中去。

在语音模型处理的过程中，会涉及 function calling，以及各种 dialog（对话日志）等。Dialog 倒好说，OpenAI 那边把 transcribe 参数打开就行，openai developer platform 平台本身也可以存；不过还有 data, privacy, compliance 的问题，这个就具体 scenario 具体分析了。

语音模型调用的 tool 再去连接自己的 business backend，包括 scheduling rules、patient appointment、各种 message 通知等。这个后端程序作为桥接，再去连诊所当前现有的 EHR 预约软件，或者连他们自己 host 的 database。一般来说，基本上任何一家企业都有些技术积累，哪怕非常老古董，但已经有现成的一套东西在跑了。能不改就尽量不改，除非有非常大的收益，否则尽量不要破坏人家原有的运行逻辑。不然让别人再去学新东西，这种认知负荷和摩擦都是很难克服的。

然后这边我还想吐槽一下。当时为了给拍片子的诊所做准备，我做了一些调研。像这种诊所，必须先收到家庭医生发来的 referral 才能预约，所以当时我准备的难点就在这里。

不得不吐槽一下安省非常混乱的医疗体系：都什么年代了，居然还得发 fax！要给这种有前置条件、必须先拿到 referral 的业务做方案，现实中做integration会遇到很大的问题。而且确实得结合当前医院现有的 IT 系统，先确定对方的 referral。

在医院场景下还有另一个问题：很多检查（比如核磁共振）都有前置准备要求，比如身上不能有心脏起搏器或金属物品，或者前一天需要禁食禁水。如果用户（client）在电话里提出这种医学问题，这里不是说像这种比较普遍、比较固定的问题，而是去问类似："我现在正在……I'm taking some medicine. Then will it be complicated? Should I stop this medicine before it?" 这种非常需要专业知识背景的问题让 AI 去回答是非常不负责任的。Anthropic 那边也强调过 delegation 的重要性：不是要 automate everything，而是要让人和 AI 在 most effective level 上进行 collaboration。

所以给诊所从0做这套东西真的很难，尤其对于我这种根本没有医学背景、全靠现场补课的人来说，肉眼可见的脑袋疼。还是那句话：像医院这种专业机构，麻烦直接去找对应的垂类 SaaS 平台，自家的工程师去做数据脱敏和效果验收。想要自己从零开始做不看现实背景，纯粹是一拍脑门的想法。

备注一下：

RAG 并不只包括 hybrid search 那一块。其实现在只要还需要走几轮、然后拿到信息的，大家都已经 general 地统称为 RAG 了。

所以不管是写 SQL 去查 database、做 function calling，还是用 MCP 或其他方式，只要是从外部获取更多信息（中间内部经过多轮turn），其实这种都算 RAG。之前只觉得 RAG 是语义空间向量检索的那种概念是错的，被教程给教窄了。

回到原话题。如果对方每天的客单量只有一两百个 call，其实一台小服务器加上 SQLite 或者 PostgreSQL 就够了，完全不用上云，不需要队列，不需要 K8s，也不需要 microservices，按照体量办事就行。

我刚才说的都是单租户。如果是多租户的情况（诊所不止一家），数据库那边的表就得改，可以按照被呼叫的号码（也就是 Twilio 的 To 参数）找到对应的诊所配置、prompt 和数据。架构上也得稍微复杂一点，要把流程拆开：之前是一整串下来，现在中间得加一个 router 来做分支。

至于诊所本身的知识，像地址、停车、营业时间、取消政策、保险这些固定的信息，直接塞进 system prompt 就行，没有检索延迟，效果也更好。

这种情况下真正需要检索的是结构化数据，比如 schedule 里的 open slots、预约信息、患者资料等。这些都要通过 tool calling 去查数据库，而不是去检索 knowledge base。

再往下谈就是更细节的代码层面了。整个流程非常清晰：

1. 先用 twilio_stream.py 拿到语音：它主要作为 audio bridge，再加上 barge-in handling。
2. 把音频送进 OpenAI Realtime：以前还要写各种 event loop、transcription 处理什么的，其实现在用 OpenAI Agents SDK 省事很多，完全不用手写那种 while 循环了。
3. 跑 Function Calling：模型那边定下来之后去调 tools.py（写哪都行，假设放这里）。里面主要放 tool definitions 加 dispatch。
4. 调度与数据库存储：再送到另外一个 .py 文件去做 scheduling。这里涉及数据库，所以会再连一个负责 database 的 .py 文件。

数据库选型方面：
虽然 SQLite 或 PostgreSQL 都能写，但考虑并发冲突，量大时 SQLite 并不好使。SQLite 本质上是单文件存储，写入时会锁住整个文件以避免冲突，其他进程就无法访问。如果每天有一两百个 call，SQLite 确实不够看，不管怎样还是 PostgreSQL 更好，它是用事务（transaction）来做 conflict handling。

最后就是处理一些杂事：保存 transcript、写 log、生成 summary 等后续收尾工作。

以及基本上所有这种 dispatch 的场景里面，再怎么着也得给人家留一个人工。那边其实可以再加一条兜底路径：如果实在搞不了，就 transfer to human。人在的情况下直接 transfer 给人工，人不在的情况下就请用户 take message（先留个言）。There's always need a fallback。

还有一个小点：因为这边用了 Twilio，所以还涉及到挂电话的问题。具体是等模型把这句说完，Twilio 那边回传 mark 事件，确定音频真的播完了，再去真正挂断或者转接。

再加上 barge-in 的问题。处理 barge-in 时，用户一开口，就要清掉 Twilio 里面没播完的音频，而且得顺手用 conversation.item.truncate 告诉模型只说到这里。不然模型真的会以为自己把那句话说完了，觉得用户听到了所有内容，并以此接着往下推理。这在实际使用中会造成很多驴唇不对马嘴的问题：比如它本来打算说“B”，但其实没说出来就被打断了，我接着往下问原本的A，它却以为我在问“它刚刚说的B”。

对不起啊，再往前说一下两种电话接入方式。最常用的是这两种：

1. 用默认的 Twilio Media Streams， 这个分 call 的 audio，然后经过我们自己的服务器，去走这个程序然后去发起一个 real-time 的 session
2. 选 OpenAI SIP：
用 Twilio Elastic SIP Trunk 直接连到 sip:<project-id>@sip.api.openai.com，OpenAI 那边会发 realtime.call.incoming 的 webhook，我们 accept 之后再去挂一个 sideband WebSocket，只处理工具调用。这个的好处是，它不用在我们的服务器上再走一轮了，直接就送到 OpenAI 那边去了，延迟会更低。


然后再谈一下合规性问题吧，反正查都查了，现在说吧。

对于医药这个方面：

1. 美国那边需要遵循的是 HIPAA：
需要跟 OpenAI、Twilio 都签 BAA，这就得走企业流程。
2. 加拿大安省需要遵循的是 PHIPA：
(a) 通话录音和转写都是 PHI（保护健康信息）
(b) 需要加密存储，并设置保留期限
(c) 需要控制访问权限
(d) 录音必须要告知对方

