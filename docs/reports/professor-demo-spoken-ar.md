# SpaceDrums professor explanation in Egyptian Arabic

3 October 2026 · Intended delivery: about 60–90 seconds at a steady conversational pace; duration has not been timed.

يا دكتور، SpaceDrums هدفه يخلّي المستخدم يعزف درامز افتراضية بكاميرا واحدة وعصايتين عاديين. والهدف البحثي إننا نتوقّع الضربة عشان نقلّل الـ action-to-sound latency، بس ده لسه ما أثبتناهوش عمليًا.

الـ V1 الحالية فيها أربع drums بترتيب اتنين في اتنين: Crash وHi-Hat فوق، وSnare وTom تحت. بنستخدم MediaPipe لتتبّع الإيدين، وPose للوقفة وقت الـ calibration، وبعد كده Computer Vision لرصد طرف العصاية. الـ calibration بتحاول تضبط الأماكن من ضربات المستخدم؛ مفيش coordinates نهائية معتمدة لحد دلوقتي.

اكتشاف الضربة حاليًا بيعتمد على حركة نازلة بتعدّي سطح الـ drum، وبيمنع تكرار نفس الضربة. مفيش temporal model شغّال في مسار الضربات الحالي.

في الـ synthetic tests، الـ 58 ضربة المتوقعة اتطابقوا كلهم، من غير ضربات ناقصة أو زيادة، لكن الاختبارات دي بتتخطّى الكاميرا. عمليًا، الوقفة نجحت، لكن تتبّع الطرف أثناء الحركة ما وفّرش ضربات كفاية لإكمال الـ calibration.

آخر قياس كان حوالي 24.8 FPS. والـ software timing كان حوالي 51 ملي ثانية median، لكن ده أثناء الـ calibration؛ الـ action-to-sound latency لسه مش متقاسة.

العائق الحالي هو الـ perception والـ performance. الخطوة الجاية بعد النهارده تقييم التتبّع بـ labels مستقلة وتحسينه قبل الاختبارات الفيزيائية الكاملة. مفيش participant results لحد دلوقتي.

Source and scope: [PROFESSOR DEMO BRIEF](C:/Users/jo/Desktop/air_drum_project/docs/reports/professor-demo-brief.md). All numerical claims refer to saved evidence; this script does not claim physical accuracy, 30 FPS or successful V1 acceptance.
